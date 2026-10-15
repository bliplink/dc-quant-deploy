# 2026-10-15 策略研究回放契约修复与 91 条缺口进度

## 结论

生产只读清单仍为 100 条 ACTIVE、当前 v4 资格合格 9 条，缺口 91 条。本轮没有发布新策略，也没有修改生产服务、策略注册表或交易参数。不能将研究预筛通过等同于正式回测通过。

原 10 月 15 日报告中的 SOL `scene_impulse_continuation_short_w8_s20_t40` 预筛 +943.44 bps 是**假阳性**：修正数据与回放契约后，同一参数验证段为 137 笔、**-179.05 bps**，不再通过。此前一次正式 SIMSvr 回测的验证段压测后 -128.250 USDT、前瞻段 -649.895 USDT，失败结论不变。不得据旧报告把它列为候选，更不得为追逐该前瞻窗口改参复测。

## 根因和修复

1. 研究回放把 K 线 `startTime` 加 15 分钟后交给场景时间轴，正式 `BacktestService.toBar` 却将数据库 `startTime` 直接作为 `BaseBar.endTime`。场景切换前后的开平仓边界因此错位。研究 CLI 现直接使用原始 `startTime`，并以场景切换精确时刻加入回归断言。
2. 旧导出从 `dc.kline FINAL` 读取 15m，存在同一 `startTime` 多行；正式查询从 `dc.kline_view` 按 `startTime ASC,(length(fmtTime)>=10) DESC,endTime DESC,fmtTime ASC LIMIT 1 BY startTime` 取唯一 K 线。导出器和研究 CLI 均改为正式选择规则；导出及预筛入口对重复／乱序时间戳 fail closed，结果元数据记录 K 线和场景输入 SHA-256。
3. 测试用本地正式回测 CLI 增加可选逐笔验证段诊断；对照错误 SOL 候选，修正时间边界后 137 笔中的 135 笔进出场一致，余下差异追溯到旧导出的重复 K 线。逐笔诊断仅供研究，默认不输出；没有修改生产撮合或发布逻辑。

新规范数据在本机 `E:\sourcecode\codex\_work\strategy-research-input-20261015`，固定窗口 `2025-10-13`～`2026-10-13`，10 品种 15m K 线和场景标签。旧 `strategy-research-input-20261014` 及基于它的预筛输出全部作废。

## 纠偏后的筛选与正式回测

规范数据上 20 批、合计 2460 个“品种 × 形态 × 风险参数”验证段组合，16 个通过。这个数字是**参数组合数**，不是 16 个独立策略：HMA、Donchian、ATR envelope、higher-timeframe pullback、volume-weighted channel 的通过组合属于此前已经用相同前瞻窗口正式判失败的家族，不能换参数／换名重新宣称成功。round26～round34 新筛选结构没有产生通过验证段的候选。

独立的 Williams %R 区间失败家族在 ADA 做多和 XRP 做空各有 3 个风险参数组合通过验证。每个品种冻结第一套预定参数（ATR14 止损 2.0、止盈 4.0）后，各只运行一次本机正式 SIMSvr v4 回测：

| 冻结候选 | 笔数 | 验证段扣费后 USDT | 前瞻段扣费后 USDT | 结论 |
| --- | ---: | ---: | ---: | --- |
| ADA Williams range failure long | 23 | +754.310417 | -368.382923 | `oos_not_passed` |
| XRP Williams range failure short | 37 | +425.968151 | -147.924266 | `oos_not_passed` |

源码及参数在 `recovery/strategy-candidates/20261015/research_r43_williams_range_failure/`。`seed.json` 故意保持 `javaSourceBase64` 为空，不能用于 INDSvr 导入或生产发布。正式结果保留在本机 `E:\sourcecode\codex\_work\strategy-local-formal-20261015` 对应 `local-pre-admission.json`；其 `productionWrite=false`。本轮**新增合格 0 条，上线 0 条**。

## 复现与后续门槛

本机验证结果在 `E:\sourcecode\codex\_work\strategy-local-validation-20261015\corrected-*`；每批 `metadata.json` 记录预筛规则、样本期、输入哈希及通过数。Python 输入断言测试 5 项通过，研究 CLI JUnit 19 项通过，代码语法与 `git diff --check` 通过。

继续补齐 91 条的正确顺序：先扩充**与已测家族结构不同**、有经济解释的信号；固定特征、品种和风险参数后只使用验证段筛选；随后在未反复使用的独立前瞻区间跑本机正式引擎，核对逐笔交易、执行成本、前瞻收益贡献和回撤；只有本机真实通过才提交 INDSvr 生成、SIMSvr 回测与发布链路。当前 `2025-10-13`～`2026-10-13` 前瞻区间已经被多轮研究使用，继续在其中大量试错会造成选择偏差。没有新的独立样本或新的经济逻辑前，不应靠增加参数排列凑足 100 条。

### 更早历史数据的可用性核查

只读检查 126：10 品种 15m K 线最早均为 `2024-08-12`，但**与正式回测契约相同的场景标签最早仅为 `2025-08-12`**。旧历史区间已按规范去重规则导出至本机 `strategy-research-input-20261015-older`，导出器的唯一时间戳检查通过；然而 `2024-08-12`～`2025-08-11` 缺少场景标签，不能直接当作场景条件策略的正式回测样本。预筛入口已增加场景首末覆盖 fail-closed 检查：旧区间预筛被明确拒绝，规范的 `2025-10-13`～`2026-10-13` 样本仍可运行。`2025-08-12`～`2025-10-12` 只有约两个月，也不足以独立覆盖 range 的 90/30/14 天完整滚动窗口。后续可研究由同一版本场景生成器回填历史标签，但需先证明规则、时间点和无未来信息，再把它用于正式判定；不能凭现有 K 线长度宣称已有一年以上的独立前瞻数据。覆盖查询脚本为 `recovery/inspect_strategy_research_coverage.py`，仅读取生产。

现有实现入口在 INDSvr 的 `HistoricalMarketSceneBackfillService`（服务端异步回填、默认持久化）及测试工具 `HistoricalSceneLocalCodexTool`（支持 `--export-snapshots-only`、`--export-rows-only` 和本机 K 线目录）。服务每个品种每天计划 00:00、12:00 两个点，并需要截至该时刻已完成的 1d/1h/15m K 线特征；首段还需要日线预热。**不得直接以默认参数启动一年、10 品种的回填**：数量约为数千个标签，涉及模型费用、批次失败处理和生产表写入。现存 `complete_historical_scenes_from_codex_training.py` 使用后期标签训练 ExtraTrees 再推导旧日期，能作探索性数据，但由于模型从未来时期学习，不能把这些衍生标签当成真正独立的历史前瞻证据。下一步应先对本机历史快照做小样本、只导出、不写库的质量与无未来信息验证，再决定是否有必要回填到生产。
