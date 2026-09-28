# DC Open API SDK Guide

> 当前状态：官方 Java / Python SDK 尚未标记为 External GA。本文定义 SDK 必须封装的行为和发布要求。

## 1. 为什么需要 SDK

当前 v1 真实传输使用：

```text
POST /api
POST /httpapi/
GW realtime transport
serverName / method / content
```

外部应用不应该重复实现复杂的认证、恢复和状态重建逻辑。

官方 SDK 应把内部 transport 细节封装成稳定开发者接口。

## 2. 推荐开发者接口

Trader 示例：

```python
client = DcTraderClient(
    api_key="...",
    secret_key="...",
    location="ABC123",
)

client.login()

order = client.place_order(
    symbol="BTCUSDT",
    side="BUY",
    order_type="LIMIT",
    quantity="0.001",
    price="60000",
)
```

Broker 示例：

```python
broker = DcBrokerClient(
    api_key="...",
    secret_key="...",
    location="ABC123",
)

broker.login()

broker.deposit(
    customer_id="customer-user-id",
    currency="USDT",
    amount="10000",
    external_ref="DEP-000001",
)

broker.place_order(
    customer_id="customer-user-id",
    symbol="BTCUSDT",
    side="BUY",
    order_type="LIMIT",
    quantity="0.001",
    price="60000",
)
```

以上是**目标 SDK API 形态**，不是当前已经发布的包名或可安装版本。

## 3. SDK 必须封装

- HMAC-SHA256 signed login
- expiry
- API Key / Session 生命周期
- permission / client type identity validation
- HTTP envelope
- routing key 构造
- Rate Limit 错误映射
- public error code 映射
- WebSocket connect / subscribe / unsubscribe
- automatic re-authentication
- automatic resubscribe
- depth snapshot + diff Gap recovery
- private state re-query after reconnect
- ClOrdID generation / idempotency helper
- Broker customer scope
- decimal string handling

## 4. 写请求重放原则

SDK 不能在网络异常后盲目重放：

- placeOrder
- cancelOrder
- cashIn
- cashOut

因为服务端可能已经接受请求，只是 response 丢失。

SDK 应通过幂等标识和查询确认结果。

读请求可以在重新认证后按白名单自动 replay。

## 5. Broker SDK 特别要求

Broker SDK 必须把以下两个身份分开：

```text
actor = Broker API Key owner
owner = customer trading account
```

所有 customer API 都需要显式 customer_id，并由服务端再次验证 location/customer ownership。

SDK 不能把 Broker actor 自己当作客户账户。

## 6. WebSocket SDK 状态机

建议：

```text
DISCONNECTED
 -> AUTHENTICATING
 -> CONNECTING
 -> CONNECTED
 -> SUBSCRIBED
 -> RECOVERING
 -> SUBSCRIBED
```

恢复完成前，应用不应把本地订单、资金、持仓状态视为权威。

## 7. SDK 计划

优先顺序：

1. Java
2. Python
3. JavaScript / TypeScript
4. Go

External GA 前最低要求：

- Java SDK
- Python SDK
- 单元测试
- Trader E2E
- Broker E2E
- reconnect E2E
- rate-limit E2E
- versioned release notes

## 8. 不应暴露的内部字段

SDK 应隐藏：

- Demo / Isdemo
- Terminal
- AlgoName
- physical service instance
- partition ID
- journal / snapshot internals

SDK 可以继续使用当前 GW transport，但开发者接口应该保持稳定。
