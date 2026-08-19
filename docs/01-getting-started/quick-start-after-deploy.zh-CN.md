# 部署后快速开始

部署完成后，建议按下面顺序验证系统。

## 1. 检查容器状态

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml ps
```

确认核心容器都处于运行状态：

- `dc-zookeeper`
- `dc-gateway`
- `dc-mdsvr`
- `dc-apssvr`
- `dc-quantsvr`
- `dc-indsvr`
- `dc-customindsvr`
- `dc-simsvr`
- `dc-batchsvr`
- `dc-web`

如果使用内置 ClickHouse，还应看到：

- `dc-clickhouse`

## 2. 检查 ClickHouse

```bash
curl 'http://127.0.0.1:8123/?query=SELECT%201'
```

检查核心表是否存在：

```bash
curl 'http://127.0.0.1:8123/?database=dc&query=SHOW%20TABLES'
```

## 3. 检查页面入口

```bash
curl -I http://127.0.0.1/web/
```

如果部署在远程服务器，请将 `127.0.0.1` 替换为服务器地址或反向代理地址。

## 4. 检查 GW/MCP

MCP 默认由 `GW` 暴露。实际地址取决于你的网关端口和网络配置。

调用 MCP 前，请在：

```text
${DEPLOY_ROOT}/control/overrides/GW/config/apiKeyList.csv
```

配置可用 API key，并重启 `gateway`。

## 5. 测试 Telegram 消息

使用 MCP 工具 `sendMsg` 发送一条纯文本消息。

示例 payload：

```json
{
  "payload": {
    "message": "DC Quant 部署验证消息"
  }
}
```

如果群里收到消息，说明 `GW -> QuantSvr -> Telegram` 链路可用。

## 6. 测试外部信号

使用 MCP 工具 `pubSignal` 发送一条最小外部信号。

示例 payload：

```json
{
  "payload": {
    "symbol": "BTCUSDT",
    "side": "BUY",
    "ocType": "OPEN",
    "price": 84250.5,
    "stopPrice": 83680.0,
    "takerPrice": 85320.0,
    "strategyName": "externalDemo"
  }
}
```

然后查询 `signal` 表，确认信号已入库。

## 7. 查看系统运行报告

`BatchSvr` 会生成系统报告。报告目录取决于镜像内配置和运行时配置，一般位于：

```text
${DEPLOY_ROOT}/data/BatchSvr/
```

日报看前一天结果，运行报告看当前状态。

## 8. 创建或导入策略

如果需要完整策略生命周期，请通过 `INDSvr` 创建 candidate，并让 `SIMSvr` 自动回测。

关键表：

- `strategy_generation_task`
- `strategy_candidate`
- `strategy_backtest_task`

## 9. 查看回测结果

回测结果主要看：

- `strategy_backtest_task`
- `backtest_result`
- `backtest_optimization_trial`

如果任务是 `SUSPENDED`，通常需要检查 K 线是否不足。

## 10. 等待自动上线

满足自动发布门槛后，`SIMSvr` 会写入：

```text
strategy_live_registry
```

上线后的策略由 `QuantSvr` 执行。
