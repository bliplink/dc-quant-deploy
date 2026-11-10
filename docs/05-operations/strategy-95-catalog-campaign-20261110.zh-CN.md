# 合格策略补齐批次：固定逻辑目录与正式回测（2026-11-10）

目标为补齐当前运行资格清单的 95 条缺口。基线为本机 `strategy-inventory-snapshot-20261110`：100 条原始 ACTIVE，近 45 天 v4 资格合格 5 条。最终完成仍以正式发布后重新审计为准。

## 固定研究批次

- 输入：`E:\sourcecode\codex\_work\strategy-research-input-20261015-extended\READY.json`，历史场景 260/260 分块完成。
- 固定验证期：2024-12-15～2025-08-11；保留期：2025-08-12～2025-10-12。
- `StrategyRepresentativeCatalogCli` 从研究库按固定声明顺序，为每个实现类和方向选择第一套参数；选择不读取行情或回测结果。
- 完整目录为 211 个实现类、418 个方向组合。10 品种 × 5 场景共验证 20,900 组，221 组通过验证段。每格按验证收益、PF 排序，并限制不同实现类，形成 52 个待审候选；实现类不同本身不保证经济逻辑独立，发布前仍需查重。
- 原始批次：`E:\sourcecode\codex\_work\strategy-95-campaign-20261110`；`campaign.json` 冻结源码、类文件、输入、协议、基线及参数哈希；`SCREEN_COMPLETE.json` 证明全部 50 格完成。原始结果均保留 `WITHHELD` 前瞻字段。

## 进入正式回测的流程

`export_representative_candidate.py` 导出选中信号实现、其父类及数学辅助函数，生成可独立编译的 `LegacyLiveSignalAdapter`。逐条调用 `RepresentativeSignalParityCli`，在原验证窗口将导出信号与研究实现逐根比较；不一致者停在执行错误，不进入财务判定。随后调用本机 SIMSvr 的正式 v4 非重叠滚动引擎，并在正式资格通过时再用同一个 `VersionedBacktestRunner` 检查完整保留期。保留期另要求至少 3 笔、PF≥1.20、最大回撤≤15%、执行压力后收益为正。每个完成结果（包括财务失败）写检查点，恢复时不得重新调参或重复测试财务失败版本。

入口：`run_representative_strategy_campaign.py`、`run_representative_formal_batch.py`。正式本机批次在 `E:\sourcecode\codex\_work\strategy-95-formal-batch-20261110`；其中的 `status.json` 和 `results.json` 才是后续进度来源。Java 子进程启动错误与策略财务失败分开记录；没有完整结果的启动错误可修复后单独重试。

本机正式结果通过后，`promote_qualified_catalog_candidates.py` 检查源码哈希、作用域、v4 资格及保留期证据，再通过 INDSvr `dc.ind.strategy.candidate.import` 导入源码。服务器重新编译和回测最近完整 365 天，由现有发布器决定是否 ACTIVE；不直接写 live registry。2026-11-10 的服务器范围固定为 2025-11-10～2026-11-09。请求、任务状态和注册表回读均保存在本机 `strategy-95-server-20261110*`，不得把本地通过数当作发布数。

## 已定位的导出与接口问题

1. 首个 ADA range 试点 v1 的数组视图错误地使用 ta4j `beginIndex`。ta4j 0.15 保留 200 根后仍可能返回 beginIndex=0，因此视图必须从 `max(beginIndex, endIndex-barCount+1)` 开始。修复后 v2 在 2,880 根 K 线上得到 93 条研究信号与 93 条导出信号，零差异；正式回测前三个验证窗口的 48 笔也与预筛一致。旧错误试点仅作排障证据，不能计入策略结果。正确 v2 因前瞻收益不通过而结束，未发布。
2. 首个 ADA channel 本地合格候选为 `catalog_adausdt_channel_982b1b51dcce`。它在本地滚动验证 35 笔、PF 1.532479、执行压力后验证收益 +387.361449、前瞻 +495.412063；独立保留期 13 笔、PF 1.494094、最大回撤 2.105%、执行压力后 +152.97812431。服务器首次因导入器强制参数名 `newKline/indicatorSymbol` 而在源代码校验阶段拒绝。提交器只做参数标识符重命名，保留本地源码哈希并记录上传源码；本地源码校验通过后再次提交。此时尚不能计作生产合格或发布完成。

策略结果应从完成检查点汇总。任何后续会话先读取本机批次状态、服务器任务及最新生产资格清单，再决定下一步；不得重复消费已检查的前瞻结果，也不得用改名、相邻风险参数或注册表直接插入补数。
