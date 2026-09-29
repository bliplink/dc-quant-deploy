# Trade 实际生命周期接入公共有界恢复：候选验收

日期：2026-09-29。Common 扩展提交 `adf16539d7146ab901ca0f5342fd853c146165c5`；Trade 接线 `4224276188efcd6cc838c154ae061e7cb2715caf`，共享快照前缀门禁 `5a870723c3b41c225dbed87a8d10e261dd263221`，最终严格启动/来源绑定门禁 `31986253ed36117104b5b67b6d3cb2f3e0fefbfb`。

**已完成实际生命周期入口的可开关接线，未启用、未晋级镜像；没有完整自动切主、API 迁移或系统 TPS 成绩。** 当前现金 API 仍是旧路径，不能因为这轮测试通过就启用其旧 SQL 写入。

## 1. 接线与不变量

TradePartitionLifecycleManager 新增默认关闭的 bounded 开关；开启时轮询只提交/观察任务，独立命名线程准备恢复。沿用现有分区业务屏障安装，再由公共 Coordinator 验证 committed prefix、当前 primary/epoch/assignment version/协议/副本及 learner、控制面连接；计划文件关闭后才 READY，再复核一次。

创建调度器之前要求 strict journal/commit/state/lifecycle/replication、控制面已连接，并校验 runtime、planner、applier、coordinator 是同一套权威来源与业务屏障。当前 `replication.required=false` 配置不能直接打开这个开关；此启动拒绝保护不等于实际副本追平、租约/CAS 或切主验收。

同分区在飞任务去重，归属变化协作取消，旧任务真正退出前不释放预算、不启动同分区新 generation。重试用单调时间；严重错误/关闭锁闭节点，不偷偷建新执行器继续晋级。去重/提交批扫描每 256 次回调及阶段边界检查 token；deadline 还覆盖 READY 发布。

保留完整预验证、资金/原结果恢复、干净尾检查；安装前后必须保持同一提交边界。整节点候选已有的“快照精确 committed prefix＋旧快照不得隐藏 v2 现金结果”校验被抽成共享方法，新生命周期也调用，防止恢复时丢掉原请求身份。不会截尾、修历史、从数据库补种或生成零余额来通过门禁。

默认并发 1、待处理 256、声明预算 128 MiB、单任务声明 64 MiB、协作 deadline 180 秒。**声明预算不是实际 heap；deadline 不是硬 IO 超时/RTO。** 阻塞的打开/快照核心解析/IO 必须返回后才能释放预算；已经常驻的全节点业务状态、直接内存、句柄和磁盘仍须单独量测。旧/当前 Trade B 384 MiB 容量门禁未因此解除。无锁外财务安装或去重淘汰。

配置与实现详见 Trade 源码 docs/TRADE_BOUNDED_RECOVERY_LIFECYCLE.md。Order/MD 尚未接这个实际 adapter；节点重试/外部读与业务门禁、可信初始账户/配置、全交易覆盖、复制一致性/投递与留存仍是完整接入门禁。

## 2. 依赖隔离与一次被拒的准备产物

不能用旧 generic 项目的 3.0.13-SNAPSHOT 替换服务 3.0.14。本轮将两个调度类打为独立本地扩展 `io.github.bliplink:com.app.cluster-recovery:3.0.14-recovery-e95850b-1`，基线 Common JAR SHA256 仍为 `542d25a3c7345c2d25806fc7c975465e96ff21ac5151dd8c35f13520c006396c`。

首次无后缀准备产物在本机重编译时，被 javac 自动拉入旧源码依赖，出现 **37 类、其中 20 类遮蔽基线**；产物被拒、前面的临时通过轮次不计为最终兼容性成绩。现在使用空 sourcepath、-implicit:none、新输出目录与新坐标，打包再白名单限制。最终 JAR/编译目录各 **17 类、基线重叠 0**，SHA256 `eaa0da8f2d405f68b99611bdf571a278e9afe88795b407e3a3c692951db01bfc`。

共享模块的 verify_extension.py 检查基线 hash、ZIP 重复/异类/遮蔽、编译目录污染和打包字节；Trade 另有运行时 CodeSource 检查，证明测试真的加载了指定基线与扩展，不只核对文件名。未发布 Central、未推送或覆盖原依赖；其他构建需要先在隔离缓存安装该本地坐标。

## 3. 实际验证与范围

- 最终 Trade **71 类 / 396 项全量 1 轮**，0 failure/error/skipped，排除已无当前源码的 1 项旧报告。
- 新接线 **19 项再重复 3 轮（57 项）**通过：类来源、实际 snapshot＋delta 恢复资金/首次结果、异步准备/去重、取消占位、同 epoch 新 version 串行、主归属变化/断连、尾漂移/脏尾、空权威目录、deadline、同业务屏障、严重错误锁闭、两个真实分区声明预算、manager 开关、旧快照隐藏现金/错误前缀拒绝、降级复制/不一致安装来源启动拒绝。
- 公共扩展对实际 Common 3.0.14 的 **2 类 / 30 项**通过；产物门禁 **6 项**通过，包含实际遇到的类污染回归。

使用本机 macOS aarch64/Zulu Java 8.0.504/Maven 3.8.7、独立复制的依赖缓存。Linux 缓存缺少 macOS Chronicle profile 的 JNA 5.8.0，补入隔离缓存（禁用 snapshot 更新）后，最终回归断网执行。测试 JVM 未套用目标容器堆/CPU 预算，因此这些成绩不能代替 Linux 新镜像或完整节点资源验收。

测试使用实际 Chronicle、snapshot、planner、业务 applier、coordinator 与屏障，但 assignment/控制面/认证为合成 fixture；原有真实 TCP/异常子进程回归也通过，**仍不是实际 ZooKeeper CAS、独立节点接管、全 API/交易计算、断电或跨故障域证明**。快照 prefix 校验可能增加历史扫描成本，须在真实副本上另量测，不能移除它换速度。

## 4. 本轮真实阻塞：测试 VM 满盘

Docker 新容器创建报 no space left on device。只读清点：VM 卷约 147 GiB/100%，运行日志约 71.3 GiB、服务数据约 41.1 GiB；其中 ProjectionSvr 当前日志约 53.8 GiB。尾部脱敏采样出现大量 GAP retry/requestGap 栈；根因、重试节流与日志限制仍需查明，不能把归档当永久修复。

8 个核心容器于 22:46（上海）只读检查仍 running、原镜像、restart/OOM 均 0；**满盘下这不证明业务可写或集群健康**。未动运行服务/配置/归属、数据库、journal、周期快照或运行日志。

本任务的 5 份已完成快照输出，确认 isolation marker/无运行容器挂载后，完整移到本机工作目录 retained-snapshot-output-20260929；五个快照迁移前后 SHA256 一致，无数据删除，隔离 journal 输入副本不动。原报告保留原路径/摘要，当前恢复位置列在新结构化证据中。这约 0.5 GiB 的可恢复转移没有解除满盘。

候选历史日志 APSSvr.log.2026-09-27 约 **4.69 GiB**：只读 /proc 检查 6056 个 descriptor，未发现该 inode 打开句柄，权限不可读进程为 0。lsof 不可用，不能把它的错误当“文件已关闭”证明；上述 inode 检查是替代证据。**尚未归档，等待用户批准；执行前必须重新检查 inode/大小/打开句柄。** 不归档活动文件，不删除历史内容，也不碰交易 journal。

## 5. 接下来

先获准可恢复归档已关闭历史日志，恢复空间并查清日志重试/增长；然后构建并核对新的 Linux 不可变镜像，在独立目录/网络/namespace 的小集群验证真实控制面、API 本地文件权威/业务 adapter 和完整资源预算。之后实际异常切换、300/16 全链路、持续系统 TPS 与负载故障/长稳。上一轮镜像/108 项成绩仅属于上一轮编码产物，不能移作本轮新接线成绩。

逐项来源、失效准备、资源门禁与归档位置：[结构化证据](evidence/trade-bounded-recovery-integration-20260929.json)。
