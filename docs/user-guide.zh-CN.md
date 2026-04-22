# 用户使用手册

本文说明部署完成后，如何理解和使用 DC Quant 的核心能力。

## 1. 策略采集

策略采集用于把外部策略素材、策略描述、外部来源数据整理成系统可处理的输入。

相关表：

- `strategy_source_raw`：原始来源数据。
- `strategy_source_norm`：规范化后的策略来源数据。

典型路径：

```text
外部素材 -> strategy_source_raw -> strategy_source_norm -> INDSvr 生成链
```

如果只使用外部信号接口，也可以不走策略采集链，直接通过 MCP `pubSignal` 发送运行时信号。

## 2. 生产策略

策略生产由 `INDSvr` 负责。常见流程：

```text
MANUAL / EXTERNAL_SOURCE / DAY_REVIEW
  -> strategy_generation_task
  -> strategy_candidate
  -> strategy_backtest_task
```

关键点：

- 新策略版本使用 `v1 / v2 / v3` 这种格式。
- 生成成功后会写入 `strategy_candidate`。
- 能进入回测的策略会创建 `strategy_backtest_task`。

常见状态：

| 状态 | 含义 |
| --- | --- |
| `PENDING` | 等待处理。 |
| `RUNNING` | 正在生成或处理。 |
| `SUCCESS` | 生成成功。 |
| `FAILED` | 生成失败。 |
| `COMPILE_FAILED` | 策略代码编译失败。 |

## 3. 策略回测

策略回测由 `SIMSvr` 负责。它会从 `strategy_backtest_task` 中拉取待处理任务。

系统使用 walk-forward 回测：

```text
fit -> validate -> forward
```

含义：

- `fit`：观察/训练窗口。
- `validate`：验证窗口。
- `forward`：前向窗口，更接近上线后的真实表现。

参数优化会产生多组 trial，并把结果写入：

- `backtest_result`
- `backtest_optimization_trial`

回测任务状态：

| 状态 | 含义 |
| --- | --- |
| `PENDING` | 等待回测。 |
| `RUNNING` | 正在回测。 |
| `SUCCESS` | 回测完成。 |
| `FAILED` | 回测失败。 |
| `SUSPENDED` | 暂停，通常是 K 线不足，等待补数后重试。 |

## 4. 回测报告

回测报告用于判断策略是否值得上线。

重点指标：

- `totalPnl`：总收益。
- `validatePnl`：验证期收益。
- `forwardPnl`：前向期收益。
- `forwardScore`：前向评分。
- `maxDrawdownPct`：最大回撤。
- `overfitPass`：是否通过过拟合过滤。

判断口径：

- validate 和 forward 都为正，可信度更高。
- forward 贡献太弱时，不建议只看总收益。
- 回撤过大时，即使收益高也需要谨慎。

## 5. 自动上线

自动上线由 `SIMSvr` 的发布逻辑完成。

上线结果写入：

- `strategy_live_registry`

常见动作：

| 动作 | 含义 |
| --- | --- |
| `PROMOTE` | 没有同名 live，首次上线。 |
| `REPLACE` | 有同名 live，新结果更优，替换上线。 |
| `SKIP` | 不满足上线门槛或不优于已有版本。 |

上线后，`QuantSvr` 会加载 live 策略参与实盘运行。

## 6. 实盘信号与外部信号

内部策略信号和外部信号最终都会进入运行时信号链。

外部信号入口：

- MCP 工具：`pubSignal`
- 后端服务：`QuantSvr`
- 数据表：`signal`

外部信号会：

```text
MCP pubSignal -> GW -> QuantSvr -> signal -> TeleStrategy -> order/trade
```

`autoSubscribeSymbol` 默认开启。若运行中的策略收到外部信号，且还没有订阅该 symbol，系统可以自动补订阅，使后续处理更接近手动选择 symbol 的流程。

实盘开仓前还会经过 `QuantSvr` 的运行时风控，包括运行状态、交易时间、仓位数量、持仓金额、多空比例、当日亏损、连续亏损、止损止盈和滑点检查。详细说明见：[QuantSvr 风控规则与 Telegram 使用说明](quantsvr-risk-telegram.zh-CN.md)。

Telegram 可用于用户设置 API、配置策略参数、启动/停止策略、查看运行状态，也可通过 MCP `sendMsg` 向固定群发送自定义消息。Telegram 群消息和外部信号审计同样由 `QuantSvr` 负责。

## 7. 日末复盘

日末复盘由 `QuantSvr` 负责，用于对信号、订单、成交、持仓做对账。

主要看：

- 信号是否产生订单。
- 订单是否成交。
- 成交是否形成完整开平仓回合。
- 日终持仓是否和交易链路一致。

复盘一般输出 JSON/HTML 文件，便于人工检查。

## 8. 系统日报与运行报告

`BatchSvr` 负责两类报告：

- 系统日报：看前一天最终结果，适合归档和复盘。
- 运行报告：看当前运行状态，通常每 5 分钟刷新一次。

日报看“结果”，运行报告看“状态”。

常见内容：

- 当前 live 策略。
- 当日 signal/order/trade/pnl。
- generation/backtest 任务状态。
- 当前异常或失败策略。
