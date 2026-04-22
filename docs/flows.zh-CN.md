# 核心流程

本文用简化链路说明 DC Quant 的主要数据流和请求流。

## 策略生成

```text
GW/API
  -> INDSvr
  -> strategy_generation_task
  -> strategy_candidate
  -> strategy_backtest_task
```

说明：

- `GW/API` 接收外部生成请求。
- `INDSvr` 负责策略生成、编译和 candidate 写入。
- 生成成功后创建回测任务。

## 回测与上线

```text
strategy_backtest_task
  -> SIMSvr
  -> backtest_result
  -> backtest_optimization_trial
  -> auto publish
  -> strategy_live_registry
```

说明：

- `SIMSvr` 拉取回测任务。
- walk-forward 和参数优化结果写入回测表。
- 满足上线门槛后写入 `strategy_live_registry`。

## 实盘运行

```text
strategy_live_registry
  -> QuantSvr
  -> signal
  -> quant_order
  -> quant_trade
  -> position / snapshot
```

说明：

- `QuantSvr` 加载 live 策略。
- 策略产生信号后进入订单和成交链路。
- 订单、成交、持仓写入 ClickHouse。

## 外部信号

```text
MCP pubSignal
  -> GW
  -> QuantSvr
  -> signal
  -> TeleStrategy
  -> quant_order / quant_trade
```

说明：

- `pubSignal` 用于第三方发送外部交易信号。
- 信号先写入 `signal` 表。
- 然后异步分发给匹配的运行中策略。
- 开仓前仍会经过 `TeleStrategy` 风控检查。

## Telegram 消息

```text
MCP sendMsg
  -> GW
  -> QuantSvr
  -> Telegram group
```

说明：

- `sendMsg` 只负责向配置的 Telegram 群发送纯文本消息。
- 群号不对外开放，固定使用 `QuantSvr` 当前配置的 `botGroupId`。
- 不写业务表，不触发交易。

## 日末复盘

```text
QuantSvr
  -> signal/order/trade/position
  -> review json/html
  -> strategy_review_fact
```

说明：

- 日末复盘检查实盘链路是否闭环。
- 结果用于人工复盘和系统日报。

## 系统报告

```text
BatchSvr
  -> ClickHouse summary
  -> system daily report
  -> system runtime report
```

说明：

- 日报统计前一天。
- 运行报告统计当前状态。
