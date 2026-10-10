# 本机 Codex 策略复核与上线记录（2026-10-10）

## 结论

- 对剩余 93 个实盘策略完成了本机生产等价回测，执行错误为 0。
- 按完整生产准入门槛重新判定后，只有 2 个策略通过：
  - `wb15_trend_t019_u70080`，`ADAUSDT / trend`；已由服务器正式回测并发布为 ACTIVE v2。
  - `research_r33_uni_median_true_range_edge_fade_short`，`UNIUSDT / range`；服务器正式回测与本机指标完全一致，但 v3 被旧的基线比较规则阻止发布，ACTIVE 暂仍为 v2。
- 其余 91 个策略没有人工绕过准入门槛。失败首因分布为：OOS 未通过 53、交易数不足 31、PF 不足 4、前瞻贡献不足 2、验证期扣费后收益非正 1。
- 权威明细在 `recovery/local-strategy-authoritative-summary-20261010.json`，包含 93 条紧凑结果和 21 条单门槛近通过候选。

## 生产等价口径

回测区间为 `2025-10-08` 至 `2026-10-08`，执行模型为
`v4_non_overlapping_walk_forward`。本机只读取生产行情和场景数据，不写生产数据库，
通过后才调用服务器 `candidate.import` 走编译、正式回测和自动发布判断。

场景窗口必须与服务器任务创建逻辑一致：

| 场景 | fit / validate / forward |
| --- | --- |
| range + 15m | 90 / 30 / 14 天 |
| breakout + 15m | 120 / 20 / 10 天 |
| reversal + 15m | 120 / 20 / 10 天 |
| trend、channel 及其他 | 120 / 30 / 14 天 |

准入条件保持生产标准：OOS 通过、交易数不少于 20、PF 不低于 1.20、最大回撤不高于
15%、验证期和前瞻期扣费后收益均为正、前瞻扣费后收益占总收益不低于 20%。

## 校准过程

第一轮 93 条虽然全部执行成功，但本机工具错误地统一使用了 `120/30/14`，导致
range、breakout、reversal 的结果不能作为生产结论。工具已修正为上述场景窗口，并对受影响的
52 条全部重跑。

校准后 `lcr1_xrp_ran_33d9206a` 的本机结果与服务器逐项一致：41 笔、PF 2.161693、
最大回撤 2.9045%、验证期扣费后收益 790.221445、前瞻扣费后收益 132.647209、
前瞻贡献 11.429%，因此不能通过 20% 门槛。这一 canary 证明修正后的本机链路与服务器一致。

## 服务器正式任务

| 策略 | 正式版本 / 任务 | 结果 | 发布结果 |
| --- | --- | --- | --- |
| `wb15_trend_t019_u70080` | v2 / `gen_1558204453448900608` | SUCCESS | 自动替换旧执行模型基线，ACTIVE v2 |
| `lcr1_xrp_ran_33d9206a` | v2 / `gen_1558204377934651392` | SUCCESS | 前瞻贡献不足，SKIP，ACTIVE v1 |
| `lcr1_eth_cha_ee700cda` | v3 / `gen_1558204455332143104` | SUCCESS | 前瞻贡献不足，SKIP，ACTIVE v2 |
| `research_r33_uni_median_true_range_edge_fade_short` | v3 / `gen_1558397928257675264` | SUCCESS | 指标通过但验证得分低于 ACTIVE 基线，SKIP，ACTIVE v2 |

UNI v3 的服务器指标与本机一致：44 笔、PF 1.354396、最大回撤 4.514%、验证期扣费后
收益 80.684097、前瞻期扣费后收益 132.683330、前瞻贡献 27.5917%。服务器同时显示
ACTIVE v2 的当前基线前瞻分数为负，但旧比较规则仍优先要求新版本验证得分更高。

SIMSvr 已增加“当前候选完整通过所有门槛且 ACTIVE 基线前瞻分数非正时允许替换”的规则。
这不是放宽候选准入，只修复退化基线长期阻塞健康候选的问题。部署后应再次 REVALIDATE UNI，
由服务器重新作出发布决定，不能手工写注册表。

## 已验证但未采用的修复

- `wb15_range_r012_u66848`（LINK）：放宽 wick sweep 后交易数由 17 增至 20，但 PF 降至
  0.905 且 OOS 失败，已撤销。
- `wb15_trend_t015_u81312`（BNB）：20 组生产参数穷举中最佳组合达到 25 笔、PF 3.9015、
  最大回撤 1.78%，但前瞻贡献仅 7.7149%，未提交服务器。

## 使用方式

1. 用 `prepare_local_strategy_queue.py` 从 live seed 和已有 v4 结果生成待复核队列。
2. 用 `run_local_strategy_batch.py` 批量执行；默认最多 4 个 worker，本轮为规避本机资源竞争使用 1 个。
3. 若需要合并修正批次，运行 `summarize_local_strategy_batches.py`，后出现的 corrected 批次覆盖同名策略。
4. 只对权威汇总中的 `qualified=true` 条目调用服务器 REVALIDATE。
5. 最终以服务器 backtest task、auto-publish decision 和 live registry 为准。

私钥口令只通过进程环境变量提供，不写入脚本、日志或仓库。
