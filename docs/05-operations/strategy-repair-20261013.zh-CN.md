# 91 个未达标策略修复记录（2026-10-13）

## 基线

确定性单 worker 回测覆盖 93 个待复核实盘策略，时间范围为
`2025-10-08` 至 `2026-10-08`。其中 2 个通过完整生产准入门槛，
91 个未通过。失败首因分布为：OOS 未通过 54、交易数不足 30、
PF 不足 3、前瞻贡献不足 3、验证期扣费后收益非正 1。

本轮不降低任何门槛，不使用 forward 窗口选参数，不写生产库。
“修复通过”必须同时满足生产 execution model、OOS、交易数、PF、
最大回撤、验证期/前瞻期扣费后收益和前瞻贡献门槛。

## 回测底座修复

- SIMSvr 增加可选 `minFitTradesPerSlice`。参数优化排序优先选择达到
  fit 样本下限的组合；全部组合都不足时优先交易数更多的组合。
- 未配置该字段时保持原排序行为，不改变已有任务。
- 长批不再预派发全部任务；基础设施执行错误达到 1 次即停止。
- `run_local_strategy_batch_chunks.py` 每个 SSH 隧道只执行 3 条，断线后
  从失败位置重试，避免把空行情误记成策略失败。
- 回测工具和批处理隧道均启用 30 秒 SSH keepalive。

## 参数级修复结论

首批样本下限参数优化显示：很多稀疏高 PF 策略在提高触发次数后，
验证期或前瞻期迅速转负。典型结果包括：

- `research_r20_ada_regression_channel_reversal_short`：10 笔扩至 47 笔后，
  PF 降至 0.8546，验证/前瞻扣费后收益均为负。
- `research_r15_ada_kama_efficiency_continuation_long`：扩至 36 笔后，
  PF 1.045，但验证/前瞻扣费后收益仍为负。
- `research_r19_link_flat_channel_wick_reentry_short`：扩至 16 笔后，
  PF 0.1386，验证/前瞻扣费后收益均为负。
- `wb15_trend_t014_u57888`：不同频率组合可到 45/125 笔，但前瞻期均亏损。

因此不能靠放宽参数把 91 个策略“凑通过”，必须区分偶然稀疏盈利和
可重复交易优势。

## 首批逻辑级修复

源码、理由和版本记录在 `recovery/strategy-repairs/manifest.json`。
7 个高潜候选全部完成编译和本机生产等价回测，没有执行错误，结果如下：

| 策略 | 交易数 | PF | 验证期扣费后 | 前瞻期扣费后 | 前瞻贡献 | 结论 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `wb15_reversal_v009_u37600` v2 | 4 | 1.878803 | 51.711760 | 2.109232 | 0.024063 | 交易数不足 |
| `lcr1_link_rev_99b035a4` v3 | 1 | 0 | -128.646295 | -208.760341 | 0 | OOS 失败 |
| `research_r20_ada_regression_channel_reversal_short` v3 | 42 | 0.708243 | -1034.841707 | -501.376175 | 0 | OOS 失败 |
| `research_r19_link_flat_channel_wick_reentry_short` v3 | 25 | 1.114186 | -153.224204 | -372.744620 | -5.228284 | OOS 失败 |
| `lcr1_btc_bre_e1e9f19e` v2 | 0 | 0 | 0 | -63.266361 | 0 | OOS 失败 |
| `lcr1_trx_ran_ec9dd240` v3 | 29 | 0.759573 | -419.798648 | -2.759959 | 0 | OOS 失败 |
| `lcr1_xrp_tre_8b8eb3e3` v3 | 19 | 3.049740 | 1054.406868 | -204.048799 | -0.166461 | OOS 失败 |

这些版本均不得提交服务器正式发布。尤其 XRP v3 虽然 PF 和验证期收益很高，
但前瞻期转负，是典型的验证期漂亮、forward 失效，必须拒绝。

## 可重复执行

1. 用 `prepare_strategy_repair_seed.py` 从确定性失败批次生成样本感知参数修复 seed。
2. 用 `prepare_logic_repair_seed.py` 从 manifest 和评审后的 Java 源码生成逻辑修复 seed。
3. 短批使用 `run_local_strategy_batch.py --tunnel-scope batch --workers 1`。
4. 长批使用 `run_local_strategy_batch_chunks.py --chunk-size 3`。
5. 用 `summarize_local_strategy_batches.py` 重复传入 `--corrected-summary`，合并所有真实批次；执行错误不会覆盖已有有效结果。
6. 只有权威汇总中 `qualified=true` 的新版本才允许进入服务器 REVALIDATE。
7. 正式提交使用 `submit_qualified_strategy_repairs.py`，必须显式给出
   `--strategy` 和 `--submit`；脚本会再次计算本地门槛并校验源码版本，
   不允许执行错误、未达标结果或错版本进入 `candidate.import`。

运行文件位于忽略目录 `recovery/strategy-repair-runs/`，仓库只保存可复跑工具、
策略修复源代码、manifest、测试和本记录，不提交大体积临时产物。
