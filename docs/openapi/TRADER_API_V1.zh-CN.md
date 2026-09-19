# DC Crypto Trader API v1

当前基线：2026-09-19。

本文面向交易员、量化程序、租户自研 Robot 和第三方交易终端。Trader API Key 的服务端 Session 类型固定为 `API`。

## 1. 快速开始

标准流程：

```text
创建 Trader API Key
    |
    v
POST /api -> LoginSvr/apiKeyLogin
    |
    v
得到 sid/token + authoritative user_id/location
    |
    +--> POST /httpapi/ 做 HTTP request/reply
    |
    +--> GW TCP/WebSocket connect
            |
            +--> requestSync/requestSyncWithKey
            +--> subscribe market/order/account topics
```

signed login 的签名、Header 和 envelope 见 [字段级调用参考](../DC_OPEN_API_V1_REFERENCE.zh-CN.md)。

连接 GW TCP/WebSocket 时，Trader 客户端使用：

```text
userName = apiKeyLogin 返回的 user_id
pwd      = apiKeyLogin 返回的 sid/token
clientType/client_type = API
Location/location      = apiKeyLogin 返回的 authoritative location
authType               = TOKEN
```

客户端不能自行把 `client_type` 改成 TenantAPI/TenantAdmin 来扩大权限。

## 2. Trader API Key 权限

允许的 scope：

| Scope | 能力 |
| --- | --- |
| `MARKET_READ` | 行情查询和行情 Topic |
| `ACCOUNT_READ` | 余额、持仓、账户配置读取和对应 Topic |
| `ORDER_READ` | 订单、成交、历史查询和私有订单/成交 Topic |
| `ORDER_WRITE` | 下单、撤单和交易配置修改 |

默认模板：

```text
MARKET_READ,ACCOUNT_READ,ORDER_READ,ORDER_WRITE
```

客户端可以在 Trader 权限域内收窄 scope，不能申请 `TENANT_READ/TENANT_WRITE`。

## 3. HTTP/TCP request/reply 方法

| Server | Method | Scope | 用途 |
| --- | --- | --- | --- |
| LoginSvr | `apiKeyLogin` | signed API key | API Key 换 Session |
| MDSvr | `queryPublicMarket` | MARKET_READ | OrderBook/Ticker/Recent Trade 聚合 |
| MDSvr | `queryKLine` | MARKET_READ | K 线 |
| OrderSvr | `placeOrder` | ORDER_WRITE | 下单 |
| OrderSvr | `cancelOrder` | ORDER_WRITE | 单笔撤单 |
| OrderSvr | `cancelBatchOrder` | ORDER_WRITE | 批量撤单 |
| OrderSvr | `queryOrder` | ORDER_READ | 订单查询 |
| OrderSvr | `queryOpenOrder` | ORDER_READ | 当前活动订单 |
| OrderSvr | `queryExecOrder` | ORDER_READ | 当前服务成交查询 |
| TradeSvr | `queryAccountBalance` | ACCOUNT_READ | 账户余额 |
| TradeSvr | `queryTradePosition` | ACCOUNT_READ | 当前持仓 |
| TradeSvr | `getAccountConfig` | ACCOUNT_READ | 账户交易配置 |
| TradeSvr | `setLeverage` | ORDER_WRITE | 杠杆设置 |
| TradeSvr | `setPositionType` | ORDER_WRITE | 持仓模式设置 |
| ProjectionSvr | `queryProjectedOrderHistory` | ORDER_READ | 持久化历史订单 |
| ProjectionSvr | `queryProjectedExecutionHistory` | ORDER_READ | 持久化历史成交 |

请求中的 `Location/UserID` 不具备提权作用；服务端以 Session 的 authoritative identity 为准。

## 4. 下单核心字段

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

金融数字在开放 API / SDK 中使用字符串表达，避免 JSON double 精度损失。

示例：

```json
{
  "serverName": "OrderSvr",
  "method": "placeOrder",
  "key": "TENANT_A|4|BTCUSDT",
  "content": {
    "SecurityID": "BTCUSDT",
    "MarketIndicator": "4",
    "Side": "BUY",
    "OCType": "OPEN",
    "OrdType": "Limit",
    "TimeInForce": "GTC",
    "OrderQty": "0.010",
    "Price": "60000.0",
    "ClOrdID": "robot-000001"
  }
}
```

OrderSvr/MDSvr 集群 routing key 的逻辑维度为：

```text
location + marketIndicator + SecurityID
```

SDK 会负责构造该 key，外部客户端不需要感知具体实例/partition。

## 5. 实时订阅

Trader 常用公开/私有 Topic：

- OrderBook / Depth snapshot / Depth diff / BookTicker / Partial Depth；
- Market Trade / Trade / Kline；
- Order status；
- Execution；
- Account balance；
- Position。

完整 Topic、image/increment、sequence、Gap、重连规则见：

[WebSocket / Topic Reference v1](WEBSOCKET_TOPICS_V1.zh-CN.md)

## 6. Session 失效与重连

当返回 `9002 / USER_SESSION_NOTEXIST` 或连接失效时：

1. 停止使用旧 Session；
2. 重新执行 signed `/api -> apiKeyLogin`；
3. 使用新 sid/token 连接 GW；
4. 重新建立行情和私有 Topic；
5. 订单/余额/持仓以重新查询和订阅 image 为准，不凭本地事件推断断线期间状态。

SDK 后续必须把上述过程封装成标准行为。

## 7. 限流、安全和错误

默认 Trader profile：

```text
TRADER_STANDARD
refill = 100 req/s
burst  = 30
```

还支持：

- API Key expiry；
- IP whitelist；
- last_used_time；
- scope 门禁；
- GW 最终错误脱敏。

公共错误码见 [字段级调用参考](../DC_OPEN_API_V1_REFERENCE.zh-CN.md#121-open-api-v1-公共错误码白名单)。

## 8. 不属于 Trader API 的能力

Trader API 不允许：

- Tenant 用户管理；
- Tenant 品种管理；
- Tenant Robot 管理；
- Tenant 设置/审计；
- 使用 Trader Session 进入 AdminSvr Tenant Control Plane。

这些能力属于 [Tenant API v1](TENANT_API_V1.zh-CN.md)。
