# 核心数据表

本文只解释部署和使用时最常查看的表。

## 策略来源

| 表 | 用途 |
| --- | --- |
| `strategy_source_raw` | 原始策略来源数据。 |
| `strategy_source_norm` | 规范化后的策略来源数据。 |

## 策略生成

| 表 | 用途 |
| --- | --- |
| `strategy_generation_task` | 策略生成任务，记录生成状态、场景、引擎、错误信息。 |
| `strategy_candidate` | 候选策略，包含策略版本、参数、编译产物和状态。 |
| `strategy_backtest_task` | 回测任务，`SIMSvr` 从这里拉取任务执行。 |

## 回测与优化

| 表 | 用途 |
| --- | --- |
| `backtest_result` | 回测汇总结果。 |
| `backtest_optimization_trial` | 参数优化 trial 明细。 |
| `backtest_slice_result` | walk-forward 切片结果。 |

## 上线

| 表 | 用途 |
| --- | --- |
| `strategy_live_registry` | 当前或历史 live 策略注册表。 |
| `strategy_release_event` | 策略发布事件。 |

## 实盘运行

| 表 | 用途 |
| --- | --- |
| `signal` | 策略信号和外部信号。 |
| `quant_order` | 订单记录。 |
| `quant_order_event` | 订单事件。 |
| `quant_trade` | 成交记录。 |
| `quant_position_snapshot` | 持仓快照。 |
| `quant_signal_block_event` | 信号被拦截或跳过的原因。 |

## 复盘和报告

| 表 | 用途 |
| --- | --- |
| `strategy_review_fact` | 日末复盘事实。 |
| `strategy_system_daily_report` | 系统日报主记录。 |
| `strategy_system_daily_report_item` | 系统日报明细项。 |

## 常用查询思路

查看生成是否成功：

```sql
SELECT * FROM strategy_generation_task ORDER BY update_time DESC LIMIT 20;
```

查看待回测任务：

```sql
SELECT * FROM strategy_backtest_task ORDER BY update_time DESC LIMIT 20;
```

查看最新回测结果：

```sql
SELECT strategy_name, strategy_version, total_pnl, forward_pnl, overfit_pass
FROM backtest_result
ORDER BY create_time DESC
LIMIT 20;
```

查看 live 策略：

```sql
SELECT strategy_name, strategy_version, status
FROM strategy_live_registry
ORDER BY update_time DESC;
```

查看外部信号是否入库：

```sql
SELECT id, strategyName, symbol, text, side, ocType, price, createTime
FROM signal
ORDER BY createTime DESC
LIMIT 20;
```

查看信号是否被风控拦截：

```sql
SELECT *
FROM quant_signal_block_event
ORDER BY createTime DESC
LIMIT 20;
```
