# CUSUM累计漂移：固定OHLCV假设与工程证明

2026-11-11，北京时间。目标仍是100条真正独立且生产合格的策略，尚未完成。本次新增一个研究机制，不是新增合格/实盘策略；没有调用DeepSeek或修改服务架构。

03:41最新接续：[正式入口已落地并启动精确父绑定队列](cusum-drift-formal-queue-20261111.zh-CN.md)。新21204/create1794339627.8894458以0/100真实等待23812完成100，10项接续专测/完整220 Python通过，21源码/797类/141工具及原oracle/数据哈希复核；只替换原槽位，不增加第5金融worker，尚未开始本批金融回放。下面“下一阶段接入”的描述为此前工程阶段的历史计划；入口已经实现，但金融仍未开始，当前manifest/身份/恢复约束以新文为准。全部顶层Python已冻结，不要再改本树脚本。

## 机制与边界：先声明，后金融

检查完整canonical研究目录后未发现CUSUM递推；原目录的短期动量、突破、收益自相关、核近邻、学得session、方向变化超越时钟均保留，不重命名为新策略。本假设用归一化已完成收益的累计偏移，既不是固定价格阈值反转，也不依赖预测标签。仍有趋势/动量共同暴露，目录不存在不证明经济独立，未来必须比较当前同单元实盘源码及实际信号。

递推参考[NIST tabular CUSUM](https://www.itl.nist.gov/div898/handbook/pmc/section3/pmc323.htm)。这里仅借用递推作交易特征：滚动尺度与重叠收益不满足经典独立同分布假设，不声称误报概率、ARL或盈利保证。

固定协议 `recovery/strategy_research_cusum_drift_protocol_20261111.json`：

- 160根热身、最多可见200根，重建最后128个完整收益。收益为当前完成close/前一完成close−1。
- 每一条收益只用其**之前**20条收益平方均值的平方根归一化；不是拟合/中心化标准差。零或非有限尺度拒绝，不回退。
- 正向 `max(0, previous + z - 0.25)`，负向 `max(0, previous - z - 0.25)`，固定参考偏移0.25、决策线5。
- 仅前一score<5且当前score>=5时按声明方向入场；不在报警后重置，不在持续高于阈值时反复入场，不用epsilon。128条重建起点为0，不冒充无限持久状态。
- 当前volume必须正，全部可见OHLC/volume必须有限、几何合法、价格正/volume非负。
- ATR14 stop1.5/take3、ATR20显式EMS保护，firstStep至少0.5%，所有step/under-trigger/under-target正值与几何不变。无可调参数、无参数网格。

多/空两方向统一一个保守机制组 `standardized_return_cusum_drift`，cohort `cusum_drift_v1`；即使扩展10品种×5场景×2方向，也是100作用域，不是100个独立策略。

## 已验证的实际工程结果

隔离Native目录 `_work/indsvr-local-cusum-drift-20261111`；隔离工具目录 `_work/dc-quant-deploy-cusum-drift-20261111`。原24052、20660、23812及其代码/数据未改，没有覆盖原SIM或IND目标类。

工程目录 `_work/strategy-cusum-drift-engineering-20261111-v1` 已完成，不是仍在跑的金融任务：

- 16项数学测试，包括64条独立路径的每个前缀与最大后缀穷举oracle完全一致；精确越界/反射/回零/不重复入场、当前收益不污染历史尺度、未来前缀不变、非法输入、风险字段原始OHLC独立算术、canonical all登记均通过。
- 两份真正导出并独立编译的BTC2023全年35040根信号/风险/退出字段原CLI对照：多535、空487，均0差异、原源码validator通过。不是零信号的一致性假通过。
- 完整原139项加新16项，155项Java回归通过。779个实际编译类、13份工程源、原validator/parity类、训练READY与全年数据、回归manifest/log哈希已复核。
- 新导出/协议6项Python测试通过；最终完整Python 210项通过，进程退出码0。前两次全量失败记录保留，见下节。

Native本地提交 `40098bbcd7af98ce5b7fdfbd74d35dec985588cc`，远端独立研究分支 `codex/local-cusum-drift-20261111` 已推 `cf13e098e3d4dee09d565e1040a136f4b6f61129`，tree `5d8700613237721c1cda7e830a4505b54ca95fd4`。5个变更blob与本地Git逐项一致，Core只加cohort/all登记4行；没有改生产latest、POM或镜像配置。

| 证据 | SHA-256 |
| --- | --- |
| 固定协议 | `740b3b6349e31c647267e1ff21214d00a699146b409b02e540aadc99f61c0332` |
| 工程manifest | `1aee7da502d093ab773a0c6b48ace9d127969b7c0a631219dcddb5a8ecfafb2b` |
| 工程完成marker | `82f5a94843b1dc570a0fc23e208303dd7cb483f90044692a0d22ba0498958525` |
| 完整回归manifest | `27f859577a10394e642e0d8f80b64db69db448d8834631ca9285868ff4a82add` |
| 完整回归log | `9963f73fbccd6677d8797cac155eb7535487c49aacc6805ce9188cf76d8571c7` |
| BTC多源码 / JAR | `952c40d476efa5482910c501d6db66b9ecb9826eecb636699f25e2365fbf6d92` / `2d6942045eee59a346fd12d1c3c3ea5dd393ed7d4f1deb6c05fde7c6305d9dd2` |
| BTC空源码 / JAR | `0bb3cc8398b08a422febc0271220b5b37d89f275d0b80275d3109f6645989f4f` / `417be18d6995a1894fdb31d126d390dfcf31f4fceeb628a04836ea7d93e19817` |
| 新行情视图READY | `1efcf589918ffcf519f4e050908f6a955490c144f3f05950b03a5d37cc61f152` |

新数据目录 `_work/strategy-cusum-drift-temporal-input-20261111` 已用原 `clone_temporal_protocol_view` 逐文件核对并复制原始市场字节，只重新绑定新协议；没有更换日期/场景、重算亏损或修改原READY。

## 如实保留的测试失败与修复范围

第一次完整208项在旧 `test_guardian_restores_exact_parent_when_handoff_owner_exits_abruptly` 失败：已读到DRAINING但立即读取OS状态仍为running；失败清理直接结束临时父进程，guardian随后操作已退出PID，并与临时目录清理争用日志。原证据保留在 `_work/strategy-cusum-drift-python-regression-failure-20261111`，没有伪装为策略亏损或忽略失败。

**仅新工具树的测试夹具**增加有界OS状态观察，仍必须真实STOPPED才继续，PID复用拒绝；finally等待精确guardian退出后才结束精确临时父进程。新增2项同步/身份测试，相关9项通过。没有修改 `research_control_handoff.py` 或任何在跑控制器。

第二次完整210项交接测试通过，但另一旧历史场景测试在退出时发生Windows临时目录清理WinError145；没有证据归因于策略逻辑或具体外部程序。相同测试单独复核通过。最后仅为该测试进程设置工作区专用TEMP/TMP后，完整210项通过并退出0；原TEMP/TMP在finally恢复，没有删除失败证据、跳过测试、重试金融回测或修改资格判断。工作区测试根为 `_work/cusum-python-test-fixtures-204a284237044a28a1e925614e85eb58`。

## 接下来必须继续，不能停在工程合格

**本批尚未启动正式金融回测，没有本地财务通过/服务器上传/发布。** 下一阶段在独立新工具树接入原 `run_case` 实际主期→严格裁决→62天独立留出链路，冻结完整100作用域、源码/JAR/协议/工程类/全部工具和输入；不得重写一个宽松执行器。

当前额外槽位已被23812方向时钟使用，原完整目录24052最多2 worker，20660也在跑。新CUSUM金融批次应绑定23812的精确PID/create/module/output/manifest，等它真实100完成及全部checkpoint/hash通过后接续这个串行槽位；资源至少3GiB可用内存，不再偷偷增加第5个金融worker、不中止任何计算子进程。若父失败或半完成，保留诊断而非将进程消失视为成功。

主期依旧2024-12-15～2025-10-12、原v4、原样本/PF/DD/OOS/扣费及至少20%前向贡献；只有主期全过才运行2025-10-13～12-13完全分离留出，不调参。只有两者均过且当前同单元源码独立性审核通过才上传固定源码126，走最近完整365日、场景/基线/发布器。固定空参数发布器格式问题仍待用户明确同意，不能加无用参数绕过。

最近生产核验仍为01:31:21北京时间的4 ACTIVE/运行资格、其中2另过贡献单项；近期4条本地严格通过均已服务器失败，不重新导入。本轮新增发布0，100条真实生产策略目标保持进行中。
