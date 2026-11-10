# CUSUM正式队列：原执行链、精确父绑定与同槽位接续

最新2026-11-11 07:07：[方向时钟完整结束，原CUSUM进程已真实接续并完成首项主回测](clock-complete-cusum-financial-start-20261111.zh-CN.md)。旧23812自然结束/完整100/0合格，21204生成并通过100检查点原父审计；原21源/797类/141工具proof与等待前完全一致，新首ADA长向467训练信号0差异，原主期27笔/PF0.796693/前向扣费-394.518526/OOS0，正常拒绝、无留出/上传。当前批次仍在跑，不重复启动21204或按旧RUNNING100状态重启23812；源码/Python冻结不改。以下03:41为历史启动快照，不是当前0/100状态。

2026-11-11 03:41，北京时间。继[工程证明](cusum-drift-research-20261111.zh-CN.md)后，正式入口已落地并启动等待进程。**当前0/100，仅排队，尚无本批金融回放、本地财务合格、上传或发布。** 100是10品种×5场景×2方向的作用域，仍只有1个保守机制组，不是100条独立实盘策略。

## 实际实现与验证

`recovery/run_cusum_drift_batch.py` 直接调用原 `run_ohlcv_profile_proxy_batch.run_case`，只传新源码工厂和7项身份字段；没有复制或重写另一个财务执行器。真实执行仍是原 `FixedSourcePrimaryReplayCli` 主期→既有严格0.20或更高贡献裁决及其余全部门槛→只有主期全过才运行 `OfflineTemporalReplayCli` 的62天分离留出。锁参空集，无参数搜索、无留出拟合，无SSH/MCP/LLM或生产写入路径。

启动前真实预检通过：21份工程/回归源码及执行配置、797个工程/原测试/validator/parity/正式引擎类、141项工具/协议/证据，原9例FIT及12例锁参证明、原训练与金融数据逐文件哈希。两方向实际源的数学/全年0差异与155 Java回归证明仍保持，未重建任何在跑SIM或IND工作树。

新增10项排队/接续测试通过，完整Python220项通过、退出0，工作区测试根 `cusum-batch-tests-6f8ecbda3528426d9a7480ac55de5a28`。测试验证：完整100作用域与单机制组、精确PID/create/module/output/manifest绑定、恢复不能换父、消失不等于完成、必须校验100份原源码/JAR/金融checkpoint、作用域/资格计数不符拒绝、实际调用原case、半完成不重跑、资源放行后向原case传全部100项、哈希变化甚至阻断helper编译。

初次10项测试有1项失败：测试全局mock `time.sleep`，除了资源等待10秒，也捕捉到原原子写入的两次0.05秒I/O退避，导致“只调用一次”断言失败。仅将测试替身限制在新batch模块的time对象，不改变运行时、I/O重试、资格条件或金融结果；10项随后通过。此为测试观察范围修正，不是被隐藏的策略失败。上一阶段208/210项的两次Windows夹具失败仍原样记在工程文档，不覆盖历史。

运行时代码本地提交 `577e8211460433cab7be7664867ccbc02a3e7e63`。新CLI在后续等待、资源等待结束前及每一作用域前复核冻结源码/类/工具；重复启动受OS排他锁保护。已有终态FAILED/FORMAL_COMPLETE直接拒绝盲跑，原case仍验证完成检查点并拒绝任何半完成尝试。

## 当前真实入口与进程身份

- PID `21204`，create_time `1794339627.8894458`，启动时间03:40:27。
- module `recovery.run_cusum_drift_batch`，工作目录 `_work/dc-quant-deploy-cusum-drift-20261111`。
- 金融根 `_work/strategy-cusum-drift-formal-20261111`；实时观察小 `status.json`、不可变候选checkpoint，勿并发读大results账本。
- 日志 `_work/strategy-cusum-drift-formal-launch-20261111/{stdout,stderr}.log`。
- 已实际验证状态 `WAITING_FOR_BOUND_CLOCK_BATCH`、0/100，唯一子进程为conhost；没有candidates/frozen/classes/FAILED，没有计算子进程。
- 自身manifest SHA `1878a3edac0508ba2811de3e5bdbc007dc709982d69b10d4e968226eaab00916`。

父绑定为**当前有效**23812/create `1794337323.3252933`/module `recovery.run_directional_clock_parallel`，目录 `strategy-directional-clock-parallel-formal-20261111`，manifest SHA `f2a7ee61d8ca590bd596cc89ef163c6af1487147a9ed6a25d16b3942ef373f16`，完整原命令也已写入新manifest。旧27328早已退休，不是新父，不能重启。

只在这个精确父进程真正结束、无FAILED、100项队列/完成marker/status一致时逐一调用原 `completed_case`：核实每份源码、JAR、seed、金融输出和原manifest归属；作用域身份及本地合格计数还必须一致。校验摘要另存 `PARENT_COMPLETION_AUDIT.json`。父消失但无完整证明会留下新FAILED，不会偷跑。

原完整目录24052最多2 worker、OHLCV20660各自继续；本批等待后替换原23812的1个串行槽位，新增金融槽位为0。沿用磁盘8GiB/内存1.5GiB底线并要求至少3072MiB可用内存、4逻辑核，每项前再查；不足等资源，不杀任何计算子进程、不降低守卫。

## 冻结证据与接续纪律

| 证据 | SHA-256 |
| --- | --- |
| 正式队列manifest | `1878a3edac0508ba2811de3e5bdbc007dc709982d69b10d4e968226eaab00916` |
| 正式入口源码 | `d05a524cd9085b0bd6c21ecb3d115fdcc14321058065ab6c65f9e4467403b158` |
| 10项专测源码 | `df7499ced9ac8b820e051e9eb9441f7b3547c05d00102bf23c82c9bff3bdfcd0` |
| 工程manifest | `1aee7da502d093ab773a0c6b48ace9d127969b7c0a631219dcddb5a8ecfafb2b` |
| 固定协议 | `740b3b6349e31c647267e1ff21214d00a699146b409b02e540aadc99f61c0332` |
| 只读数据READY | `1efcf589918ffcf519f4e050908f6a955490c144f3f05950b03a5d37cc61f152` |
| 原9例实际FIT oracle | `5b29252b6355097ae408dddef3ca0cc02f89d3b3c39339ce03253db7ee551399` |
| 原12例实际锁参oracle | `5ef0221d51f94bab334fb9be0d9a1fea1e581d5f7b2cbc3c4416fad8f82704e7` |

本工具树**全部顶层Python文件均已被运行manifest冻结**，不要在这里继续改脚本/测试；后续新研究必须新建隔离树，文档/新脱敏观察摘要可以增补。不要用修改预期SHA接受不同helper，不重启旧队列或重放损失/半完成窗口。

下一会话先实查21204的PID/创建时间/完整命令/output与实际子进程，再实查23812及其小status；观察超时不代表终止，不要另外启动。只出现新的完整本地严格主期+独立留出合格，才做当前生产源码独立性复核并上传固定源码126走正常最近完整365日、场景/基线/发布器；既有失败候选不得重导入。固定空参数发布格式修复仍待用户明确同意，不得用无用参数绕过。

最近生产核验仍为01:31:21北京时间的4 ACTIVE/运行资格，其中2另过贡献；这不是4条全过新发布要求。当前本轮新增发布0，100条真实生产合格策略目标仍进行中。
