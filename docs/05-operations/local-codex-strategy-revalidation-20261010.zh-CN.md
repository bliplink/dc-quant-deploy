# 本机 Codex 策略复核与上线记录（2026-10-10）

## 结论

- 对剩余 93 个实盘策略完成了单 worker、确定性行情输入的本机生产等价回测：完成 93，执行错误 0。
- 完整生产准入门槛下只有 2 个策略通过：
  - `wb15_trend_t019_u70080`，`ADAUSDT / trend`，服务器正式回测并发布为 ACTIVE v2。
  - `research_r33_uni_median_true_range_edge_fade_short`，`UNIUSDT / range`，服务器正式回测并发布为 ACTIVE v5。
- 其余 91 个策略没有人工绕过准入门槛。失败首因分布为：OOS 未通过 54、交易数不足 30、PF 不足 3、前瞻贡献不足 3、验证期扣费后收益非正 1。
- 权威明细为 `recovery/local-strategy-authoritative-summary-20261010.json`，包含 93 条紧凑结果和 21 条仅差一个门槛的候选。

## 生产等价口径

回测区间为 `2025-10-08` 至 `2026-10-08`，执行模型为
`v4_non_overlapping_walk_forward`。本机只读取生产行情和场景数据，不写生产数据库；
通过后才调用服务器 `candidate.import`，由服务器完成编译、正式回测和自动发布判断。

场景窗口与服务器任务创建逻辑一致：

| 场景 | fit / validate / forward |
| --- | --- |
| range + 15m | 90 / 30 / 14 天 |
| breakout + 15m | 120 / 20 / 10 天 |
| reversal + 15m | 120 / 20 / 10 天 |
| trend、channel 及其他 | 120 / 30 / 14 天 |

准入条件保持生产标准：OOS 通过、交易数不少于 20、PF 不低于 1.20、最大回撤不高于
15%、验证期和前瞻期扣费后收益均为正、前瞻扣费后收益占总收益不低于 20%。

## 校准与确定性修复

第一轮 93 条虽然全部执行成功，但本机工具错误地统一使用 `120/30/14`，导致
range、breakout、reversal 的结果不能作为生产结论。工具已按上述场景窗口修正并重跑。

随后发现同一 UNI 源码和参数的正式回测偶发得到 44 笔或 45 笔交易。根因是
`dc.kline_view` 按 `fmtTime` 聚合，而两条数据链使用了完整日期时间和 `HHmmss` 两种格式，
同一个 `startTime` 会保留两条且 OHLC 可能不同。UNI 区间内原视图返回 36,334 行，
实际只有 35,136 个唯一 `startTime`，即 1,198 个重复时间点。

SIMSvr 的 `BacktestQueryService` 已改成每个 `startTime` 只选择一条确定性 K 线：优先完整
`fmtTime`，再按 `endTime` 和 `fmtTime` 固定排序；计数也改成 `uniqExact(startTime)`。
同一 UNI 候选连续正式回测 v6、v7 指标完全一致，确认消除了输入顺序抖动。该修复提交
`d2814d3` 已构建并部署到生产 SIMSvr。

校准后的 XRP canary 也与服务器逐项一致：41 笔、PF 2.161693、最大回撤 2.9045%、
验证期扣费后收益 790.221445、前瞻扣费后收益 132.647209、前瞻贡献 11.429%，
因此正确地被 20% 门槛拦截。

## 服务器正式任务

| 策略 | 正式版本 / 任务 | 结果 | 发布结果 |
| --- | --- | --- | --- |
| `wb15_trend_t019_u70080` | v2 / `gen_1558204453448900608` | SUCCESS | 自动替换旧执行模型基线，ACTIVE v2 |
| `lcr1_xrp_ran_33d9206a` | v2 / `gen_1558204377934651392` | SUCCESS | 前瞻贡献不足，SKIP，ACTIVE v1 |
| `lcr1_eth_cha_ee700cda` | v3 / `gen_1558204455332143104` | SUCCESS | 前瞻贡献不足，SKIP，ACTIVE v2 |
| `research_r33_uni_median_true_range_edge_fade_short` | v3 / `gen_1558397928257675264` | SUCCESS | 旧基线比较规则阻止发布 |
| 同上 | v4 / `gen_1558401480946409472` | SUCCESS | 重复 K 线顺序抖动导致费用后验证收益为负，未发布 |
| 同上 | v5 / `gen_1558402010938662912` | SUCCESS | 完整通过并自动发布，ACTIVE v5 |
| 同上 | v6 / `gen_1558404267809759232` | SUCCESS | 与 v5 指标相同，SKIP |
| 同上 | v7 / `gen_1558404652268052480` | SUCCESS | 与 v5、v6 指标相同，SKIP |

UNI 稳定指标为：44 笔、PF 1.354396、最大回撤 4.514%、验证期扣费后收益
80.684097、前瞻期扣费后收益 132.683330、前瞻贡献 27.5917%。

SIMSvr 同时修正了退化基线比较：当前候选完整通过所有门槛且 ACTIVE 基线前瞻分数非正时，
允许健康候选替换退化基线。这不放宽候选准入，只防止负前瞻基线长期阻塞已完整达标的新版本。

## 已验证但未采用的修复

- `wb15_range_r012_u66848`（LINK）：放宽 wick sweep 后交易数由 17 增至 20，但 PF 降至
  0.905 且 OOS 失败，已撤销。
- `wb15_trend_t015_u81312`（BNB）：20 组生产参数穷举中最佳组合达到 25 笔、PF 3.9015、
  最大回撤 1.78%，但前瞻贡献仅 7.7149%，未提交服务器。

## 使用方式

1. 用 `prepare_local_strategy_queue.py` 从 live seed 和已有 v4 结果生成待复核队列。
2. 用 `run_local_strategy_batch.py` 批量执行。默认为 1 个 worker；本机资源充足时可显式提高，但最多 4 个。
3. 用 `summarize_local_strategy_batches.py` 生成紧凑权威汇总；如传入修正批次，后者覆盖同名策略。
4. 只对权威汇总中 `qualified=true` 的条目调用服务器 REVALIDATE。
5. 最终以服务器 backtest task、auto-publish decision 和 live registry 为准。

私钥口令只通过进程环境变量提供，不写入脚本、日志或仓库。
