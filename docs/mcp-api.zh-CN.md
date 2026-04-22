# MCP 接口说明

本文只说明部署后对第三方最常用的 MCP 工具。真实对外地址、API key 和网络访问策略由部署方提供。

## 调用约定

- MCP 服务由 `GW` 对外提供。
- 调用方必须在 HTTP header 中传入 `apikey`。
- API key 必须在 `GW` 的 `apiKeyList.csv` 中授权到对应工具。
- 请求体使用 MCP `tools/call` 规范，业务参数放在 `payload` 中。

## pubSignal

用途：发布一个外部交易信号。系统会写入 `dc.signal`，再交给运行中的策略消费。

必填字段：

- `symbol`：交易品种，例如 `BTCUSDT`。
- `side`：方向，按系统原始枚举传入，例如 `BUY`、`SELL`。
- `ocType`：开平仓，按系统原始枚举传入，例如 `OPEN`、`CLOSE`。
- `price`：信号价格。
- `stopPrice`：止损价格。
- `takerPrice`：止盈价格。
- `strategyName`：外部策略名，由调用方提供。

可选字段：

- `text`：周期，默认 `15M`。
- `strategyVersion`：默认 `v1`。
- `scene`：默认 `external`。
- `strategyPayload`：默认 `{}`。
- `venueTypeGW`：默认 `BNFutures`。
- `type`：订单类型说明，可传 `limit` 或 `market`，不传时沿用系统默认。
- `orderExpireSeconds`：挂单有效时间，未传时沿用当前系统默认挂单时间。
- `autoSubscribeSymbol`：是否自动订阅品种，外部信号默认 `true`。
- `remark`：备注。

最小业务参数示例：

```json
{
  "payload": {
    "symbol": "BTCUSDT",
    "side": "BUY",
    "ocType": "OPEN",
    "price": 84250.5,
    "stopPrice": 83680.0,
    "takerPrice": 85320.0,
    "strategyName": "partnerRangeBreak"
  }
}
```

带订单类型和挂单有效时间示例：

```json
{
  "payload": {
    "symbol": "BTCUSDT",
    "side": "BUY",
    "ocType": "OPEN",
    "price": 84250.5,
    "stopPrice": 83680.0,
    "takerPrice": 85320.0,
    "strategyName": "partnerRangeBreak",
    "type": "limit",
    "orderExpireSeconds": 300
  }
}
```

## sendMsg

用途：向系统配置的 Telegram 群发送一条纯文本消息。

字段：

- `message`：必填，非空字符串。

示例：

```json
{
  "payload": {
    "message": "最新交易播报\n策略：xl\n品种：BTCUSDT\n方向：多头开仓"
  }
}
```

## 配置位置

MCP 工具配置：

```text
control.prod.example/overrides/GW/config/mcpTools.tsv
```

API key 授权配置：

```text
control.prod.example/overrides/GW/config/apiKeyList.csv
```

生产环境请使用真实 key，并且不要把真实 key 提交到仓库。
