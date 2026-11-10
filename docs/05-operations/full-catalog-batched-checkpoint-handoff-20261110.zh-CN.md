# 完整目录回测：安全检查点交接及启动合并实装

2026-11-10 23:48北京时间，仍只用既有OHLCV、不改服务架构，不调用DeepSeek生成/修复。目标100条真实独立合格策略尚未完成；此记录证明研究执行接续，不是盈利、策略数量或生产发布证明。

## 已实际完成的交接

原完整目录调度器12040（2026-11-10 21:38:37创建）已交接至24052（23:47:11创建，psutil create_time=1794325631.2460444）。先核对原PID/创建时间/完整命令/module/output及冻结计划，挂起的仅是本地Python调度父进程；原计算子进程保持运行。待所有计算子进程自然退出、逐项检查点验证完整后，才终止原父进程并取得同一原目录的OS排他锁。没有终止Java/金融子进程、重启服务器或修改交易/风控。

- 实际复用115条已完成金融观察，含全部失败；没有重放这些结果。
- HANDOFF_INTENT.phase=TRANSFERRED；原12040已不存在。
- 原目录OS锁实测被新调度器持有，第二个调度器无法取得。
- checkpoint SHA `c4d4ae2ecea4a171524a9bdc842c15597b6bd5c100f45b1c5ddd55a10e96e84f`。
- controller manifest SHA `a2c87580b6555aff2319837a623be049a8216486f24f75044e9351ea51600026`。
- 原19,599项完整队列、次序、401项预留/已消费排除集、规则、数据、原helper、正式引擎及费用门槛不变；原计划SHA仍 `59944b8d1fcb4f504cb129e29c49956da064e5c6270bce1409b47b6db2a1c347`，未改写。

23:48检查：新目录已完成117/19,599、原始通过0、严格通过0，两个真实独立作用域worker在运行、errors空，可用内存3399MiB。新调度确实已产生至少两条新金融结果，不只是准备脚本或单元测试。另一平衡批次4332不作切换，236/400、原始通过1（该LINK源服务器已失败），仍运行。

## 改变与不变

`run_fit_risk_catalog_batched`复用原完整队列，先验证所有原tool/input/class/proof哈希与完整400源/1600档证明，再强制[8例32档启动合并训练证明](four-profile-launch-batching-20261110.zh-CN.md)。新源码合同仍由原导出器生成、原编译器编译，使用同一个原源码/逐字段信号校验器，只把5次JVM启动合为1次。新合同以明确schema、wrapper和proof哈希留痕，不冒充旧工具输出。

正式金融仍调用未修改的 `recovery.run_fit_risk_admission`，每个作用域拥有独立目录/JAR/classes/JVM；原主期、验证必要门槛、完整v4、锁参分离62天留出都不改。旧raw DTO零默认缺陷不在运行中改helper，所有通过候选另经既有0.20或更高门槛的只读strict裁决，并保持时序/源码/种子参数与真实验证spec一致。

只允许1或2个worker；默认2。入场调度先检查空闲磁盘至少8GiB和可用内存至少1536MiB，已有一个活跃任务时第二个要求至少2304MiB可用内存；低资源则等待，不杀计算来“恢复”。队列分发不按新收益重新排序，完成账本按原队列顺序写。没有自动服务器提交，合格源仍需当前同行机制复核和正常服务器发布门槛。

所有每项合同/admission继续存放原目录，保留旧日志；新控制器只写自己的新日志/aggregate/状态。这样即使控制器异常退出，完成结果仍可验证复用；部分金融目录会明确阻止重跑，不能凭日志或过期观察超时重新启动。

## 崩溃和错误保护

单独 `research_control_handoff` guardian在暂停旧父进程前READY。若交接控制器突然退出，它仅恢复原精确PID/创建时间/命令匹配的父调度器，不触及子进程；覆盖暂停与下一次意图落盘之间的窗口。检查点验证失败或等待子进程超时也恢复旧调度器，不执行接管。真实测试已验证子进程自然完成、无NEXT任务启动、检查点失败恢复、控制器被终止后的guardian恢复。

新worker发生执行错误时停止分发新项，但让其他已在跑项自然结束并保存；不terminate/kill、不删除部分记录或盲目重试。FAILED出现后必须诊断，不能直接`--resume`掩盖。本次工程测试曾遇Windows测试临时日志句柄关闭时序及测试fixture缺计划文件，均在真实交接之前修正，最终11项交接/调度测试及全量168项Python通过，不涉及金融失败重算。

## 接续入口（优先级已变化）

新实时状态/日志：

- `_work/strategy-fit-risk-full-catalog-batched-controller-20261110/status.json`：小状态含raw/strict计数及每个worker真实PID/创建时间/命令。
- `_work/strategy-fit-risk-full-catalog-batched-launch-20261110/stdout.log`、`stderr.log`。
- controller目录下`HANDOFF_INTENT.json`、`HANDOFF_CHECKPOINT.json`、`manifest.json`、`adjudications/`。
- 原`strategy-fit-risk-full-catalog-20261110/CONTROL_HANDOFF.json`指向新控制器；原status可能仍显示115/RUNNING，仅历史状态，不能据此重启12040。

原金融证据仍在`strategy-fit-risk-full-catalog-20261110/admissions`，合同在其`contracts`（BTC/trend复用主目录证明），不读取/打印并发大aggregate。每项原完成marker和源/JAR/金融哈希均须再次验证。不得删除原计划、旧失败或部分执行目录。

重接首先核实24052真实进程及输出身份，不以lock文件/状态文件单独认定存活。若进程仍活着就监控同一进程，不再启动；如已退出，先看真实FAILED/complete、原金融部分目录及遗留计算进程，再决定如何接续。代码的`--resume`要求同一已冻结manifest/参数、TRANSFERRED且原父进程不存在，重新取得两个OS锁并扫描所有逐项终态；并不授权恢复任何不完整金融尝试。

最近服务器库存仍以23:33:40的[LINK服务器失败后快照](fit-risk-link-server-admission-20261110.zh-CN.md)为准：4条运行资格、另2条通过贡献单项，本轮没有服务器发布。后续新严格通过候选必须另审机制/服务器最近完整365日，不能将本地任务、方向、风险档或版本凑成100条。
