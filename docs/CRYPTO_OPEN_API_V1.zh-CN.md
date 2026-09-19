# Crypto Open API v1 设计基线

当前基线：2026-09-19。

## 1. 当前阶段目标

本阶段只完善现有 **加密货币永续/保证金交易模型** 的开放 API，不修改现有撮合、资金、持仓、Funding、强平、保险基金和 ADL 计算模型，也不改变 `marketIndicator` 的语义。

`marketIndicator` 继续作为市场/品种市场标识；外部 API 同时使用 `symbol/securityId + marketIndicator` 识别交易市场。未来扩展外汇、商品、债券、自定义交易品种时，在保持 Open API 基本兼容的前提下再扩 Instrument/Product 元数据。

当前 Open API 的目标用户有两类：

1. **Trader API Key**：租户交易员、量化程序、租户自研 Robot。
2. **Tenant Service API Key**：租户自己的管理后台、自动化运维和后续自研行情 Adapter。

平台提供的 Trade Web、Tenant Web、Platform Web、APSSvr 和 RobotSvr 都不是开放 API 的强依赖；租户可以完全脱离这些 UI/可选服务，通过 API 使用交易核心。

## 2. 推荐运行架构

```text
Internet / Tenant Network
        |
        | HTTPS / WSS
        v
+-----------------------+
|   L7 Load Balancer    |
+-----------+-----------+
            |
    +-------+-------+
    |               |
    v               v
OpenApiSvr-1     OpenApiSvr-N       <-- 无状态，可横向扩展
    |               |
    +-------+-------+
            |
            | internal GW protocol / keyed routing
            v
            GW
   +--------+---------+----------------+
   |                  |                |
   v                  v                v
LoginSvr          MDSvr Cluster    OrderSvr Cluster
                                      |
                                      v
                                  TradeSvr Cluster
                                      |
                                      v
                                    LiqSvr
```

`OpenApiSvr` 不承担撮合、资金和风险计算，只做：

- REST/WSS 协议；
- API Key HMAC 校验；
- API Key scope / IP allowlist / expiry；
- rate-limit；
- 请求参数标准化；
- API versioning；
- 外部错误码/HTTP 状态码；
- 将外部请求映射为内部 GW 请求；
- 将内部 topic/event 映射为稳定的外部 WebSocket stream。

因此 OpenApiSvr 可以水平扩容，不改变 Order/MD/Trade 的一致性边界。

## 3. API Key

### 3.1 类型

Trader key 默认：

```text
MARKET_READ
ACCOUNT_READ
ORDER_READ
ORDER_WRITE
```

Tenant service key 默认：

```text
MARKET_READ
ACCOUNT_READ
ORDER_READ
ORDER_WRITE
TENANT_READ
TENANT_WRITE
```

保留的后续 scope：

```text
APIKEY_READ
APIKEY_WRITE
MARKET_WRITE        # 第二阶段 Tenant Market Ingress
```

### 3.2 元数据

`dc_users_api` 当前扩展：

```text
location
user_id
api_key
secret_key
type
permissions
ip_whitelist
expires_at
rate_limit_profile
label
last_used_time
```

私钥仅在创建成功时返回一次；查询 API Key 列表不得返回 `secret_key`。

### 3.3 外部签名

Open API v1 采用每请求 HMAC，不把内部 GW session/token 暴露给 API 客户端。

请求头：

```text
X-DC-API-KEY
X-DC-TIMESTAMP
X-DC-RECV-WINDOW
X-DC-SIGNATURE
```

签名原文：

```text
timestamp + "\n"
+ HTTP_METHOD + "\n"
+ PATH + "\n"
+ RFC3986_SORTED_QUERY + "\n"
+ SHA256_HEX(RAW_BODY)
```

签名：

```text
hex(HMAC-SHA256(secret_key, canonical_request))
```

规则：

- 默认 `recvWindow=5000ms`；
- v1 最大允许 `60000ms`；
- key 过期、禁用、scope 不足、IP 不在 allowlist、时间窗超限均 fail-closed；
- 外部 `location/userId` 在私有接口中不是权威字段，必须从 API Key 身份解析；
- OpenApiSvr 内部可缓存 API session，但 API 客户端不感知内部 session。

## 4. REST API v1

统一前缀：

```text
/openapi/v1
```

### 4.1 Public market

| HTTP | Path | Scope | 内部来源 |
| --- | --- | --- | --- |
| GET | `/ping` | public | OpenApiSvr |
| GET | `/time` | public | OpenApiSvr |
| GET | `/exchangeInfo` | public | AdminSvr / tenant symbol rules |
| GET | `/depth` | public | MDSvr `queryPublicMarket` / depth image |
| GET | `/trades` | public | MDSvr recent trades |
| GET | `/ticker/price` | public | MDSvr ticker |
| GET | `/ticker/bookTicker` | public | MDSvr BBO |
| GET | `/klines` | public | MDSvr `queryKLine` |
| GET | `/markPrice` | public | MDSvr tenant mark/index |

公共行情必须显式携带 `location`，因为不同租户可以启用不同产品/行情源。输入还包括 `marketIndicator` 和 `symbol`。

### 4.2 Trader private trading

| HTTP | Path | Scope | 内部映射 |
| --- | --- | --- | --- |
| POST | `/order` | ORDER_WRITE | OrderSvr `placeOrder` |
| DELETE | `/order` | ORDER_WRITE | OrderSvr `cancelOrder` |
| GET | `/order` | ORDER_READ | OrderSvr `queryOrder` |
| GET | `/openOrders` | ORDER_READ | OrderSvr `queryOpenOrder` |
| GET | `/allOrders` | ORDER_READ | ProjectionSvr projected history / OrderSvr history |
| GET | `/myTrades` | ORDER_READ | ProjectionSvr projected execution history |
| GET | `/account` | ACCOUNT_READ | Trade/Projection account view |
| GET | `/balance` | ACCOUNT_READ | Trade account balance image |
| GET | `/positionRisk` | ACCOUNT_READ | Trade position image |
| POST | `/leverage` | ORDER_WRITE | TradeSvr `setLeverage` |
| POST | `/positionMode` | ORDER_WRITE | TradeSvr `setPositionType` |

Private API 不接收可覆盖身份的 `location/userId`。OpenApiSvr 从 API Key 得到 authoritative `location + user_id`，再写入内部请求。

### 4.3 API Key self-service

| HTTP | Path | Scope |
| --- | --- | --- |
| POST | `/apiKeys` | APIKEY_WRITE 或交互式登录 session |
| GET | `/apiKeys` | APIKEY_READ 或交互式登录 session |
| DELETE | `/apiKeys/{apiKey}` | APIKEY_WRITE 或交互式登录 session |

首个 key 仍可由 Trade Web / Tenant Admin 交互式会话创建。API Key 不能通过自身权限任意提升自己的 scope。

## 5. Tenant API v1

统一前缀：

```text
/tenant/v1
```

Tenant API Key 的 location 永远来自 key，不接受调用方切换租户。

| HTTP | Path | Scope | 当前内部能力 |
| --- | --- | --- | --- |
| GET | `/users` | TENANT_READ | `tenantUserAdmin.LIST` |
| POST | `/users` | TENANT_WRITE | `tenantUserAdmin.CREATE` |
| POST | `/users/{id}/enable` | TENANT_WRITE | `ENABLE` |
| POST | `/users/{id}/disable` | TENANT_WRITE | `DISABLE` |
| POST | `/users/{id}/reset-password` | TENANT_WRITE | `RESET_PASSWORD` |
| GET | `/symbols` | TENANT_READ | `tenantSymbolAdmin.LIST` |
| POST | `/symbols/{symbol}/enable` | TENANT_WRITE | `ENABLE` |
| POST | `/symbols/{symbol}/disable` | TENANT_WRITE | `DISABLE` |
| GET | `/robots` | TENANT_READ | `tenantRobotAdmin.LIST` |
| POST | `/robots` | TENANT_WRITE | `UPSERT` |
| PUT | `/robots/{id}` | TENANT_WRITE | `UPSERT` |
| POST | `/robots/{id}/enable` | TENANT_WRITE | `ENABLE` |
| POST | `/robots/{id}/disable` | TENANT_WRITE | `DISABLE` |
| GET | `/settings` | TENANT_READ | `tenantSettingsAdmin.GET` |
| PUT | `/settings` | TENANT_WRITE | `tenantSettingsAdmin.UPDATE` |
| GET | `/audit` | TENANT_READ | `tenantSettingsAdmin.AUDIT` |
| GET | `/orders` | TENANT_READ | `tenantTradeAdmin.ORDERS` |
| GET | `/executions` | TENANT_READ | `tenantTradeAdmin.EXECUTIONS` |
| GET | `/positions` | TENANT_READ | `tenantTradeAdmin.POSITIONS` |
| GET | `/balances` | TENANT_READ | `tenantTradeAdmin.BALANCES` |

平台级 API 与 Tenant API 分离，不允许 Tenant API Key 访问 PLATFORM scope。

## 6. Order request v1

外部字段采用稳定 API 名，OpenApiSvr 转为现有 `NewOrderSingle`：

```json
{
  "symbol": "BTCUSDT",
  "marketIndicator": "4",
  "side": "BUY",
  "positionSide": "LONG",
  "type": "LIMIT",
  "timeInForce": "GTC",
  "quantity": "0.010",
  "price": "60000.0",
  "clientOrderId": "my-bot-000001",
  "reduceOnly": false
}
```

映射：

```text
symbol          -> SecurityID
marketIndicator -> MarketIndicator
side            -> Side
positionSide    -> PositionSide / OPEN-CLOSE normalization
type            -> OrdType
timeInForce     -> TimeInForce
quantity        -> OrderQty
price           -> Price
clientOrderId   -> ClOrdID
```

数值全部使用十进制字符串，禁止 JSON double 作为金融权威输入。

`clientOrderId` 继续复用现有 OrderSvr 幂等性机制；重试同一业务请求不得生成重复订单。

## 7. WebSocket v1

### 7.1 Public

```text
/openapi/v1/ws/public?location=<tenant>
```

订阅：

```json
{"method":"SUBSCRIBE","params":[
  "depth:4:BTCUSDT",
  "trade:4:BTCUSDT",
  "ticker:4:BTCUSDT",
  "kline:4:BTCUSDT:1m"
],"id":1}
```

### 7.2 Private

```text
/openapi/v1/ws/private
```

握手使用与 REST 相同的 API Key + timestamp + signature。身份来自 key。

私有 stream：

```text
order
execution
position
balance
account
```

外部 stream 名称稳定，内部 topic 名称不得成为公开兼容性契约。

## 8. Rate limit

至少支持配置文件：

```text
READ_ONLY
TRADER_STANDARD
TRADER_HIGH
TENANT_STANDARD
TENANT_HIGH
```

v1 计量维度：

```text
api_key
location
source_ip
endpoint_group
```

响应头：

```text
X-DC-RATE-LIMIT
X-DC-RATE-REMAINING
X-DC-RATE-RESET
```

超限返回 HTTP 429。

多 OpenApiSvr 实例时不能只依赖单进程全局计数。第一版可以使用 API-key consistent-hash/sticky routing 保证单 key 进入固定 OpenApiSvr；生产多活阶段再引入共享 rate-limit store。

## 9. 错误语义

HTTP 层使用：

```text
400 INVALID_REQUEST
401 INVALID_API_KEY / INVALID_SIGNATURE / REQUEST_EXPIRED
403 PERMISSION_DENIED / IP_NOT_ALLOWED / TENANT_DISABLED
404 ORDER_NOT_FOUND / SYMBOL_NOT_FOUND
409 DUPLICATE_CLIENT_ORDER_ID / STATE_CONFLICT
429 RATE_LIMITED
503 ROUTE_NOT_READY / PARTITION_NOT_READY / SERVICE_UNAVAILABLE
```

业务响应：

```json
{
  "code": "ORDER_NOT_FOUND",
  "message": "order does not exist",
  "requestId": "01...",
  "serverTime": 1789830000000
}
```

不得把 Java exception、SQL、ZK path 或内部 serverName 暴露到公网响应。

## 10. 横向扩展

OpenApiSvr 不保存资金/订单权威状态，可任意水平扩：

```text
OpenApiSvr x N
   |
   +-- public market -> MDSvr keyed route
   +-- order         -> OrderSvr market placement
   +-- account       -> TradeSvr location partition
   +-- tenant admin  -> AdminSvr
```

Order/MD 继续按 `location + marketIndicator + securityId`；Trade 继续按 `location`。Open API 层不重新发明分区算法。

## 11. 第二阶段：租户自研行情

本阶段只预留 `MARKET_WRITE` scope，不立即开放写行情。

下一阶段增加：

```text
/ingress/v1/book
/ingress/v1/trade
/ingress/v1/ticker
/ingress/v1/mark-price
```

Tenant Market Adapter 与平台 APSSvr 最终进入同一个 MDSvr 规范化入口。

## 12. 多资产兼容原则

Open API v1 不把“永续”写入 URL；只在当前实现的 `exchangeInfo` 中表明产品属性。以后扩展 FX、商品、债券或租户自定义品种时，继续复用：

```text
symbol/securityId
marketIndicator
side
order type
quantity
price
clientOrderId
tenant identity
```

再增加可选 instrument metadata，而不重新设计下单 API。
