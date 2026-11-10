# CUSUM完整训练证明矩阵：已启动，尚未完成或启用复用

2026-11-11 04:38，北京时间。100条真实生产合格策略目标仍未完成。[单BTC试验](cusum-identity-training-pilot-20261111.zh-CN.md)之后，本次已实现并实际启动完整训练矩阵；当前只核验首个完成组，**不是100份证明已完成，更不是100条合格/实盘策略**。

## 完整范围与实现

工具目录 `_work/dc-quant-deploy-cusum-parity-matrix-20261111`，本地代码提交 `265cd8fe5284add90d57e1c56cd328ab13f85821`。`verify_cusum_identity_matrix.py` 必须覆盖10个原品种×2方向×5场景；没有缩小范围的CLI选项。20个品种/方向参考组各重新执行原CLI的2023全年35040根对照，不跨品种/方向借用信号结果，也不只复用旧BTC数字。

每组：真正导出、独立编译、原validator校验五份源码，绑定各自JAR、seed、场景优化配置；与同组参考作精确源码/完整3类文件身份等价检查。参考窗口固定2023-01-01～12-31，原源码/16数学/64独立fixture/155 Java回归与前一试验正反例证据全部保持。只允许声明package/返回标签身份差异；源/数值/风险/字节码不符即失败。

最终必须有20个真实全年参考、100份独立源码/JAR/validator记录、全部组checkpoint，覆盖身份/上下文一致，源码/JAR/seed/log最终再校验一遍，才能写MATRIX_COMPLETE。各场景fit/validate/forward配置仍独立绑定；**证明可复用的是训练对照，不是不同场景的金融结果**。

环境绑定包括939项关键源码/工具/工程类、完整2280个类路径class、68个运行时JAR及Java工具、11份训练输入（READY+10品种）。每组前后核对完整类路径成员和字节，不能新增JAR/类后继续用旧证明。每个重JVM阶段前继续要求3072MiB可用内存、4逻辑核、原磁盘8GiB/内存1.5GiB底线，资源不足如实等待，不杀计算子进程、不调整资格门槛。

## 真实预检错误与修复

最初238项Python全量回归通过，但真实文件预检发现 `KeyError: symbols`：这个原训练READY的品种成员声明在 `files`，不是金融READY的 `symbols`。只修新工具读取真实schema，并增加专门回归；没有给旧READY补字段、修改原数据或换预期SHA。原训练TSV约103104/103584行，包含2023之外的训练前缀，不能误认为每个文件本身仅35040行；实际CLI按2023日期过滤且必须得到35040根。

修复后10项矩阵专测、完整239项Python回归通过、退出0。测试包括20组完整场景覆盖、缺失/重复拒绝、固定策略白名单、真实训练schema、全年对照输出验证、跨品种/方向/政策拒用、100份记录与参考/上下文一致、原源码/JAR/seed/validator与每场景参数绑定。工作区临时根 `cusum-matrix-tests-fixed-20ecf4b8dd6245fe85dcc0b4826d0a5e`。

## 运行入口，必须核对实际身份

- PID `3948`，create_time `1794342593.785792`，04:29:53启动，module `recovery.verify_cusum_identity_matrix`。
- 工作目录 `_work/dc-quant-deploy-cusum-parity-matrix-20261111`。
- 输出 `_work/strategy-cusum-identity-matrix-20261111-v1`；读取小status和不可变 `groups/<symbol>/<long|short>/GROUP_COMPLETE.json`，不要并发读大矩阵账本。
- 日志 `_work/strategy-cusum-identity-matrix-launch-20261111/{stdout,stderr}.log`。
- matrix manifest `a074c787bacd4a61f605113303636f76c4ca42dcb4e5f6867ddd036ced908e02`。
- context SHA `7ef5634ee42c5ee6d14c66bc4afe8a2b99b7494a490426dfa7856e75470a9864`。

已实际确认进程身份、OS工作仍进行；04:37时1/20组、5/100份证明已完成，第二组在计算/资源等待。证明父进程驻留约49MiB、峰值约115MiB，并非自身数百MiB缓存导致的假等待；没有清理用户程序或调低守卫。

## 首个完成组：ADAUSDT多头

`groups/ADAUSDT/long` 的原始全年参考与五个场景文件、源码/JAR/seed/validator/字节码证明已逐项只读核验：35040根、467个信号、0差异。没有金融期、独立留出、服务器上传或发布。场景优化配置确实不同：trend/channel、range、breakout/reversal分别绑定其原窗口，不能据字节等价混同场景资格。

| 证据 | SHA-256 |
| --- | --- |
| 首组完成marker | `b4afcb260d2de6842084958da86a10a2e93eef2860e1fc032fbdafcba1c224dd` |
| 首组canonical记录 | `7092356e0d116b0d79fb9874e5f9e8f9d2b6fe164b6e1e60d9775651d8a139a1` |
| 首组原CLI全年log | `85add75b145f398fa663b48872509cccee09ce6036b46e7eeea50533af96aaa1` |
| 首组canonical源码 | `a64578b6202d947cf0593afecba76a965643571e43eaaf713ad0201646ab89c0` |
| 首组canonical JAR | `6da6484b83cebdde8ab136c573d8e8ba0c35c1a08742c971c090d1ae3371365f` |
| 矩阵入口源码 | `507d180de1aae226b28c76652899d77608df9a9b2e89bb15f84eb6000ec0e839` |
| 矩阵专测源码 | `f6a61ca8ef41880f4c291dcb72539bb67ada4fff815627c447a585387c3bacdc` |

## 接续纪律与尚未完成项

runtime_reuse_enabled=false；runtime_admission_ready=false。本矩阵未完成，不能先启用部分证明或宣称已加速正式队列。下一会话先实查3948的精确PID/创建时间/module/output及真实子进程；等待资源是正常状态，不因观察超时重启。已有输出目录或部分尝试拒绝盲跑，全部原失败/日志保留。

本树所有顶层Python已经被矩阵context冻结，**不要边运行边改脚本/测试**；后续缓存准入/交接开发必须另建工作树。只有完整20组/100份证明及所有哈希通过，才实现显式证据复用并单独验证安全交接；不能直接覆盖旧金融控制器或跳过其主期、严格贡献、分离留出。

当前真正金融队列仍为21204（CUSUM0等待23812），23812方向时钟、20660 OHLCV、24052完整目录继续；没有交接、暂停、重启或修改它们。旧27328及已结束的单例5200不要重启。新本地严格主期+独立留出合格才可固定源上126走最近完整365日及场景/基线/发布器；固定空参数发布格式修复仍待用户明确同意。新增实盘仍0，100条真实策略目标继续。
