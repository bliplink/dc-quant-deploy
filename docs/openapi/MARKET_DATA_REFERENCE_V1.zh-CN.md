# DC Market Data API Reference v1

> HTTP 行情查询与实时行情入口参考。  
> 当前 Crypto 基线默认 `MarketIndicator=4`。

---

# 1. Query Public Market

查询公开市场快照。

## Permission

`MARKET_READ`

## Server / Method

```text
serverName = MDSvr
method     = queryPublicMarket
```

## Rate Limit

```text
Weight: 1
Scope: session
```

## Request

```json
{
  "serverName": "MDSvr",
  "method": "queryPublicMarket",
  "content": {
    "location": "ABC123",
    "securityID": "BTCUSDT"
  }
}
```

## Request Parameters

| Field | Type | Required | Description |
|---|---|---:|---|
| location | string | Yes | 当前租户 location；服务端仍以 Session scope 为权威 |
| securityID | string | Yes | 交易品种 |

## Response

当前返回聚合：

- Order Book
- Ticker
- Recent Trades

具体字段以 MDSvr 当前 DTO / OpenAPI schema 为准。

## Client Guidance

Public Market 适合：

- 首次页面 image
- reconnect 后状态恢复
- 低频快照

高频更新建议使用 WebSocket，不建议通过 HTTP 高频轮询。

---

# 2. Query Kline

查询 K 线。

## Permission

`MARKET_READ`

## Server / Method

```text
serverName = MDSvr
method     = queryKLine
```

## Rate Limit

```text
Weight: 1
Scope: session
```

> 当前还没有按 Kline 返回数量设置 method weight。

## Request

```json
{
  "serverName": "MDSvr",
  "method": "queryKLine",
  "content": {
    "location": "ABC123",
    "securityID": "BTCUSDT",
    "start": "",
    "end": "",
    "text": "1m",
    "num": 500
  }
}
```

## Request Parameters

| Field | Type | Required | Description |
|---|---|---:|---|
| location | string | Yes | 当前租户 |
| securityID | string | Yes | 品种 |
| start | string | No | 开始时间 |
| end | string | No | 结束时间 |
| text | string | Yes | Kline 周期，如 `1m` |
| num | integer | No | 返回数量 |

当前历史 Kline 主数据链为 ClickHouse；客户端不应直接访问 ClickHouse。

---

# 3. Realtime Market Streams

实时行情通过 GW WebSocket / Topic。

当前稳定候选：

```text
dc.md.orderbook.<SecurityID>.<Location>
dc.md.trade.<SecurityID>.<Location>
```

以及公开行情能力：

- OrderBook / Depth
- BookTicker
- Trade
- Kline

完整规则：

`docs/openapi/WEBSOCKET_TOPICS_V1.zh-CN.md`

---

# 4. Snapshot + Delta

推荐客户端模型：

```text
HTTP snapshot
   +
WebSocket delta
   =
local market state
```

如果检测到：

- sequence gap
- reconnect
- subscription reset

应重新查询 snapshot，然后继续应用增量。

---

# 5. Current Namespace Limitation

当前部分 market topic 尚未编码 `MarketIndicator`。

因此未来开放：

```text
同一个 SecurityID
跨多个市场
```

前，需要升级 topic namespace，并提供兼容期。

---

# 6. Common Errors

| Code | Msg |
|---:|---|
| 5004 | SYMBOL_NOT_FOUND |
| 9002 | USER_SESSION_NOTEXIST |
| 9004 | PARAMETER_ERROR |
| 10003 | RATE_LIMIT_EXCEEDED |
| 10004 | ACCESS_DENIED |
| 9000 | INTERNAL_ERROR |
