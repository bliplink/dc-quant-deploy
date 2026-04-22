# 报告与排障

本文汇总常见问题的判断入口。

## 回测失败怎么看

先看：

```text
strategy_backtest_task
```

常见状态：

| 状态/原因 | 含义 | 处理方式 |
| --- | --- | --- |
| `COMPILE_FAILED` | 策略代码编译失败 | 查看生成任务和编译日志。 |
| `INSUFFICIENT_KLINE` | K 线不足 | 补齐对应 symbol/text/dateRange 的 K 线后等待重试。 |
| `Java heap space` | 回测内存不足 | 降低并发、增大 JVM 堆、减少 trial。 |
| `SUSPENDED` | 暂停等待恢复 | 多数是数据不足，不应直接当作失败。 |

## 为什么策略没有上线

常见原因：

- `validatePnl <= 0`
- `forwardPnl <= 0`
- `totalPnl <= 0`
- `forwardScore <= 0`
- `overfitPass = false`
- 新策略没有优于已有 live baseline

排查表：

- `backtest_result`
- `backtest_optimization_trial`
- `strategy_live_registry`
- `strategy_release_event`

## 为什么外部信号写库成功但没有下单

可能原因：

- 没有运行中的策略订阅该 `symbol + text`。
- 策略收到信号但风控或状态判断跳过。
- `autoSubscribeSymbol` 只在信号已经到达策略实例后生效，不能替代上游匹配。
- 账户、交易所或下单链路异常。

排查顺序：

```text
signal -> QuantSvr 日志 -> quant_signal_block_event -> quant_order -> quant_trade
```

更完整的运行时风控说明见：[QuantSvr 风控规则与 Telegram 使用说明](../03-user-guide/quantsvr-risk-telegram.zh-CN.md)。

## Telegram 怎么使用

用户入口：

- `/start` 打开主菜单。
- 先设置 API 账号。
- 再设置策略参数，例如策略模式、交易品种、仓位金额、最大持仓、运行时间、止盈止损、当日最大亏损和连续亏损次数。
- 启动策略后，`QuantSvr` 才会消费匹配的信号并进入下单链路。

群消息：

- 交易播报、外部信号审计、自动订阅提示会发送到 `botGroupId`。
- 第三方可通过 MCP `sendMsg` 发送一条自定义纯文本群消息。

## 为什么 MCP 调不通

检查：

- 请求是否带 HTTP header `apikey`。
- `apiKeyList.csv` 是否包含该 key 和目标工具权限。
- `mcpTools.tsv` 是否配置了工具。
- `GW` 是否重启加载了新配置。
- 后端服务是否注册到 Zookeeper。

## 为什么 Telegram 中文乱码

中文乱码通常发生在调用方或网关请求编码阶段。

建议：

- 调用方统一使用 UTF-8。
- HTTP 请求明确发送 `Content-Type: application/json; charset=utf-8`。
- 先看 `GW` 日志，再看 `QuantSvr` 日志，判断乱码在哪一跳出现。

如果业务成功但消息乱码，说明业务链路可用，编码链路仍需单独修。

## 为什么系统日报没生成

常见原因：

- `BatchSvr` 在日报 cron 时间点没有运行。
- 服务使用内存型调度，停机期间错过的 cron 不会自动补跑。
- 报告目录权限或路径配置错误。
- 数据表被清空或当天没有可统计数据。

排查：

- `BatchSvr.log`
- 报告输出目录
- `strategy_system_daily_report`
- `strategy_system_daily_report_item`

## 为什么运行报告和日报内容不同

这是正常设计：

- 日报看前一天最终结果。
- 运行报告看当前时刻状态。

运行报告适合盯盘，日报适合复盘。

## 为什么容器启动但服务不可用

检查：

- `docker logs <container>`
- `${DEPLOY_ROOT}/log/<Service>.log`
- 端口是否被占用。
- `control/ATSConfig.ini` 中注册地址是否正确。
- `control/DBPoolConfig.ini` 中 ClickHouse 地址是否正确。
- Zookeeper 是否可用。
