# DC Crypto Open API v1 基线

当前基线：2026-09-19。

## 1. 设计结论

当前阶段**不新增 OpenApiSvr**，也**不把交易/行情/账户业务塞进 GW 或 AdminSvr**。

DC Open API v1 直接产品化现有 GW HTTP/WebSocket/TCP 能力：

```text
Trade Web / Tenant Web / Trader Robot / Tenant Backend / SDK
                         |
                  HTTP / WebSocket
                         |
                         v
                    GW Cluster
                         |
        +----------------+----------------+
        |                |                |
     LoginSvr          MDSvr          OrderSvr
      Auth/API          Market           Orders
                                          |
                                          v
                                       TradeSvr
                                   Account / Risk
                                          |
                                          v
                                        LiqSvr

     AdminSvr                     ManagerSvr
 Tenant Control Plane          Platform Control Plane

                ProjectionSvr
          Durable order/trade history
```

职责边界：

- **GW**：连接、HTTP/WebSocket/TCP、request/reply、pub/sub、服务发现、负载均衡、keyed routing、通用安全/限流；不实现订单、资金、租户、Robot 等业务。
- **LoginSvr**：登录、Session、API Key Source of Truth。
- **MDSvr**：行情权威服务。
- **OrderSvr**：订单/撮合权威服务。
- **TradeSvr**：资金、持仓、手续费、保证金、风险权威服务。
- **LiqSvr**：强平/保险基金/ADL。
- **AdminSvr**：Tenant Control Plane。
- **ManagerSvr**：Platform Control Plane。
- **ProjectionSvr**：历史订单/成交投影查询。

平台自己的 Web 与第三方 API 客户端复用相同后端服务接口。外部客户端不需要知道具体 Order/Trade/MD 节点、partition、primary/replica 或 epoch。

## 2. 当前阶段范围

v1 先完整开放当前加密货币永续/保证金能力：

- 行情；
- 下单/撤单/订单查询；
- 成交查询；
- 余额/持仓/账户设置；
- API Key；
- 租户用户/品种/Robot/设置/审计；
- HTTP + WebSocket/TCP 订阅；
- Order/MD/Trade 集群透明路由。

本阶段不改：

- `marketIndicator` 语义；
- 当前 perpetual margin/risk/funding/liquidation 模型；
- OrderSvr/TradeSvr/MDSvr 的核心业务模型。

未来扩 FX、商品、债券和租户自定义品种时继续复用 `marketIndicator + SecurityID` 和同一 GW/API 框架，再增加 Instrument/Product 元数据。

## 3. 两类 API Key

### 3.1 Trader API Key

用途：

- 交易员量化程序；
- 租户自研 Robot；
- 第三方交易终端。

默认能力：

```text
MARKET_READ
ACCOUNT_READ
ORDER_READ
ORDER_WRITE
```

Trader key 不允许申请 Tenant scope。

### 3.2 Tenant Service API Key

用途：

- 租户自己的管理后台；
- 租户自动化运维；
- 第二阶段 Tenant Market Adapter。

默认能力：

```text
MARKET_READ
TENANT_READ
TENANT_WRITE
```

Tenant Service key 不拥有 `ORDER_WRITE`。租户自研 Robot 应使用独立交易用户 + Trader API Key，而不是 Tenant Admin key 下单。

### 3.3 v1 细粒度权限策略

阶段 2 已开放**受控的 scope 子集**，并完成逐方法运行时门禁：

- `updateApiKey` 仍由服务端强制生成 `type=trade`，但允许客户端从 Trader scope 集合中选择子集：`MARKET_READ,ACCOUNT_READ,ORDER_READ,ORDER_WRITE`；
- `tenantApiKeyAdmin.CREATE` 仍由服务端强制生成 `type=tenant`，但允许客户端从 Tenant scope 集合中选择子集：`MARKET_READ,TENANT_READ,TENANT_WRITE`；
- 未提交 `permissions` 时仍使用对应默认模板；
- Trader key 申请 Tenant scope、Tenant Service key 申请 Trader scope 会 fail-closed；
- `rate_limit_profile` 仍由服务端控制，客户端不能自行扩大限流档位；
- Trader API Session 的服务端类型为 `API`，Tenant Service API Session 的服务端类型为 `TenantAPI`；
- OrderSvr、TradeSvr、MDSvr、ProjectionSvr、AdminSvr 已按方法/动作检查所需 scope；
- OrderSvr/TradeSvr 继续硬拒绝 `TenantAPI`；AdminSvr Tenant Control Plane 继续只接受 `TenantAdmin` 和 `TenantAPI`。

因此权限模型同时具备“key class 硬隔离 + 精确 scope 门禁”，客户端只能收窄权限，不能跨权限域提权。

### 3.4 当前 API Key 元数据

`dc_users_api`：

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

规则：

- key 与 `location + user_id` 绑定；
- Trader 自助创建只能生成 `type=trade`；
- Tenant Service key 只能由 TENANT_ADMIN 控制面创建；
- 查询 key 不返回 `secret_key`；
- 过期 key 在 LoginSvr fail-closed；
- `ip_whitelist` 已在 GW signed `/api` 入口强制执行：空白名单表示不限制；非空白名单支持单个 IPv4/IPv6 与 CIDR，格式非法或来源不匹配均 fail-closed；
- 当前 SaaS 直连部署以 Netty socket peer 作为权威来源 IP，不信任客户端自行提交的 `X-Forwarded-For`；未来若在 GW 前增加反向代理/LB，必须同时配置可信代理链路后再启用代理头；
- `rate_limit_profile` 由服务端按 API Key 类型分配，客户端不能选择、更改或提升级别；当前 SaaS 部署策略为 `TRADER_STANDARD = 100 req/s`、burst `30`，`TENANT_STANDARD = 20 req/s`、burst `10`；
- GW 使用独立 token bucket：`req/s` 是持续补充速率，`burst` 是瞬时桶容量，因此 Trader 并不表示可在瞬间发送 100 个请求，默认瞬时容量为 30；
- 该 profile 只约束 `API`/`TenantAPI` Session 的业务请求；signed `/api` 的 API Key 登录交换本身不使用该 Session profile，`WEB`/`TenantAdmin` 也不受这两个 Open API profile 控制；
- `last_used_time` 在 API Key 通过身份/location/enable/expiry 等校验并成功创建 API/TenantAPI Session 后更新；失败认证不会刷新该时间；
- `last_used_time` 是安全审计元数据，不在每笔订单、行情、账户等 Session 业务请求上写数据库，因此不会把高频业务流量转换成高频审计写；该审计字段持久化失败只记录服务端错误，不把已成功创建的 API Session 反向判为登录失败；
- 私有业务请求中的 `Location/UserID` 不是权威身份，下游服务仍由 Session 覆盖并校验冲突。

## 4. GW HTTP 协议

DC Open API v1 **保留现有 GW envelope**，不强制改造成 Binance REST 路径。

### 4.1 API Key 签名入口

默认入口：

```text
POST /api
Content-Type: application/json
```

Headers：

```text
cid: <client request id>
apikey: <api key>
expiry: <epoch milliseconds>
signature: <hex hmac>
```

Body：

```json
{
  "serverName": "LoginSvr",
  "method": "apiKeyLogin",
  "content": {
    "api_key": "xxxxxxxx",
    "location": "TENANT_A",
    "cid": "robot-auth-001"
  }
}
```

当前签名算法与 `com.app.common.ApiKeyUtils` 保持一致：

```text
signature =
  HEX(
    HMAC-SHA256(
      secret_key,
      UTF8(raw_http_body + expiry)
    )
  )
```

`expiry` 为毫秒时间戳；当前服务端至少校验请求在 expiry 前到达。SDK 推荐使用短期 expiry，例如当前时间 + 60 秒。

**v1 推荐流程：API Key 先调用 `LoginSvr/apiKeyLogin` 换取 Session，然后后续交易/账户请求使用 Session。** 这与当前 RobotSvr 已验证的真实链路一致。

LoginSvr 会把以下 API Key 上下文作为 Session 权威快照返回并持久化：

```text
api_key_type
permissions
rate_limit_profile
```

Trader key 示例为 `trade + MARKET_READ,ACCOUNT_READ,ORDER_READ,ORDER_WRITE + TRADER_STANDARD`；Tenant Service key 示例为 `tenant + MARKET_READ,TENANT_READ,TENANT_WRITE + TENANT_STANDARD`。Session refresh/resume 保留同一快照；升级前没有权限快照的 `API/TenantAPI` Session 不恢复，客户端需要重新执行 signed API-key login。

这里的 `permissions` 是**权威会话字段**。阶段 2 已完成 Order/Trade/MD/Projection/Admin 的运行时 scope 门禁；Session refresh/resume 只能保留原快照，不能扩大权限。

### 4.2 Session HTTP

入口：

```text
POST /httpapi/
sessionId: <LoginSvr returned session>
Content-Type: application/json
```

Body：

```json
{
  "serverName": "OrderSvr",
  "method": "queryOpenOrder",
  "content": {
    "SecurityID": "BTCUSDT",
    "MarketIndicator": "4"
  }
}
```

私有请求即使携带 `Location/UserID`，OrderSvr/TradeSvr/AdminSvr 仍使用 Session 中的 authoritative tenant/user identity。

## 5. DC Open API v1 服务目录

### 5.1 Authentication / API Key — LoginSvr

| method | 用途 | 权限 |
| --- | --- | --- |
| `apiKeyLogin` | API Key 换 Session | signed API key |
| `updateApiKey` | Trader 自助创建/更新 key | interactive trader session |
| `queryApiKey` | Trader key 列表 | interactive trader session |
| `deleteApiKey` | 删除 Trader key | interactive trader session |
| `tenantApiKeyAdmin` | Tenant Service key LIST/CREATE/DELETE | TENANT_ADMIN |

### 5.2 Market API — MDSvr

| method/topic | 用途 | Scope |
| --- | --- | --- |
| `queryPublicMarket` | order book + ticker + recent trades | MARKET_READ/public tenant market |
| `queryKLine` | K 线 | MARKET_READ |
| market order-book topic | 深度 image/update | MARKET_READ |
| market trade topic | 逐笔成交 | MARKET_READ |

Market 请求至少由：

```text
location
marketIndicator
SecurityID
```

确定租户市场。私有登录后的 location 仍以 Session 为准。

### 5.3 Trading API — OrderSvr

| method | 用途 | Scope |
| --- | --- | --- |
| `placeOrder` | 下单 | ORDER_WRITE |
| `cancelOrder` | 单笔撤单 | ORDER_WRITE |
| `cancelBatchOrder` | 批量撤单 | ORDER_WRITE |
| `queryOrder` | 单笔/条件订单查询 | ORDER_READ |
| `queryOpenOrder` | 当前活动订单 | ORDER_READ |
| `queryExecOrder` | 当前服务成交查询 | ORDER_READ |

Order/MD 集群请求使用：

```text
routing key =
location + marketIndicator + SecurityID
```

SDK/客户端不自行计算实际 partition owner，只需要向 GW 提供完整的市场身份字段。

### 5.4 Account / Risk API — TradeSvr

当前可复用：

```text
queryAccountBalance
queryTradePosition
getAccountConfig
dc.trade.accountbalance.**
dc.trade.position.**
setLeverage
setPositionType
order preview / account config APIs
```

职责：

- balance；
- position；
- margin/risk；
- leverage；
- position mode；
- liquidation-related state。

所有金融计算结果以 TradeSvr 为权威；客户端或 AdminSvr 不重新计算。

### 5.5 Durable History — ProjectionSvr

| method | 用途 | Scope |
| --- | --- | --- |
| `queryProjectedOrderHistory` | 历史订单 | ORDER_READ |
| `queryProjectedExecutionHistory` | 历史成交 | ORDER_READ |

查询强制 `location + userId` 边界。

### 5.6 Tenant API — AdminSvr

| method | action | Scope |
| --- | --- | --- |
| `tenantUserAdmin` | LIST/CREATE/ENABLE/DISABLE/RESET_PASSWORD | TENANT_READ/TENANT_WRITE |
| `tenantSymbolAdmin` | LIST/ENABLE/DISABLE | TENANT_READ/TENANT_WRITE |
| `tenantRobotAdmin` | LIST/UPSERT/ENABLE/DISABLE | TENANT_READ/TENANT_WRITE |
| `tenantSettingsAdmin` | GET/UPDATE/AUDIT | TENANT_READ/TENANT_WRITE |
| `tenantTradeAdmin` | ORDERS/EXECUTIONS/POSITIONS/BALANCES/... | TENANT_READ |
| `tenantUserRegistration` | 租户公开注册 | public + tenant registration policy |

Tenant API 不允许通过 body 切换 `location`。AdminSvr 使用 LoginSvr Session 的 location 作为权威租户。

### 5.7 Platform API — ManagerSvr

Platform API 只面向平台运营身份，不属于 Tenant API Key 权限域。

包括：

- tenant application/approval；
- tenant lifecycle；
- quota；
- tenant service route；
- cluster snapshot；
- placement preview/apply。

## 6. Order 消息

v1 直接使用现有 `NewOrderSingle` 语义，不再额外维护一份 Binance DTO。

核心字段：

```text
SecurityID
MarketIndicator
Side
OCType
PositionSide
OrdType
TimeInForce
OrderQty
Price
ClOrdID
ReduceOnly
```

例：

```json
{
  "serverName": "OrderSvr",
  "method": "placeOrder",
  "content": {
    "SecurityID": "BTCUSDT",
    "MarketIndicator": "4",
    "Side": "BUY",
    "OCType": "OPEN",
    "OrdType": "Limit",
    "TimeInForce": "GTC",
    "OrderQty": "0.010",
    "Price": "60000.0",
    "ClOrdID": "tenant-robot-000001"
  }
}
```

金融数值在开放文档/SDK 中使用字符串，避免客户端 JSON double 精度问题。

## 7. WebSocket / TCP API

GW 已经提供连接、登录、request/reply、subscribe/unsubscribe。

API Key 客户端标准流程：

```text
1. HTTP /api -> LoginSvr/apiKeyLogin
2. 得到 user_id + location + session token
3. GateWayApi/WebSocket connect，client_type=API
4. requestSync / requestSyncWithKey
5. subscribe market/order/trade/account topics
6. 断线后重新认证/重连/重新订阅
```

平台 RobotSvr 当前已按该流程真实运行，可作为 Java SDK 行为基线。

示例 execution topic：

```text
dc.order.trade.<SecurityID>.*.<UserID>.<Location>
```

示例 market trade topic：

```text
dc.md.trade.<SecurityID>.<Location>
```

后续会把全部公开 topic、image/increment、sequence、Gap、重连语义整理成单独 WebSocket/Topic Reference。内部未正式纳入 v1 目录的 topic 不承诺兼容。

## 8. 集群透明性

外部 API 不暴露：

```text
OrderSvr-A/B/C
MDSvr-A/B/C
TradeSvr-A/B
partition id
epoch
primary/replica
ZooKeeper path
```

GW 和服务端路由负责：

- Order/MDSvr：`location + marketIndicator + SecurityID`；
- TradeSvr：`location`；
- primary/replica/fencing/recovery。

因此同一套 API 可直接随着 GW / Order / MD / Trade 横向扩展。

## 9. 错误与兼容

所有对外方法必须固定：

- request/response 字段；
- code/msg 语义；
- 必填/可选字段；
- 幂等字段；
- scope；
- topic；
- version。

GW 已作为 DC Open API v1 的最终错误响应边界。signed `/api`、`API`/`TenantAPI` Session 以及匿名公共行情响应均执行公共错误白名单：

- `code=0` 的成功响应保持业务数据不变；
- 白名单错误保留公开 `code`，但 `msg` 强制转换成固定公共消息，错误 `data` 清空；
- 非白名单 code、无法解析的响应、内部异常统一转换为 `9000 / INTERNAL_ERROR / data=null`；
- `cid` 在可安全识别时保留，便于客户端与服务端日志关联；
- WEB/TenantAdmin 内部产品链路不受 Open API 脱敏策略影响。

公开错误码的唯一清单见《DC Crypto Open API v1 调用参考》和 `docs/openapi/crypto-openapi-v1.yaml`。服务端日志可以保留完整异常用于排障，但以下内容不得进入 Open API 错误响应：

- Java exception / stack trace；
- SQL / JDBC / 数据库内部信息；
- 文件路径、类名；
- ZooKeeper path；
- 容器名、实例名；
- partition owner / 内部集群状态细节。

现有内部 handler 可以继续演进，但一旦某方法正式进入 `DcOpenApi.VERSION=v1`，破坏性修改必须通过 v2 或兼容字段完成。新增公共错误码必须先加入 GW whitelist、OpenAPI YAML 和公开参考文档，不能直接透传内部错误码。

## 10. 第二阶段：Tenant Market Ingress

当前只先完成 Crypto Open API。

下一阶段给 Tenant Service key 增加受控：

```text
MARKET_WRITE
```

并开放租户自研行情 Adapter：

```text
book snapshot/delta
trade
ticker
index
mark price
```

平台 APSSvr 与 Tenant Market Adapter 最终都写入同一套 MDSvr 规范化行情入口。

## 11. 多资产演进

未来 FX、商品、债券和租户自定义品种继续复用：

```text
GW transport
API Key
location
marketIndicator
SecurityID
OrderSvr
MDSvr
TradeSvr
```

再逐步扩 Instrument/Product/Risk/Settlement 模型。Open API v1 不因为资产类别扩展而重新发明一套网络协议。
