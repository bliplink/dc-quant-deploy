# 2026-10-11 Order/Trade Common 状态机：真实生命周期绑定及提交日志适配

## 当前已落地

沿用统一架构：Common 拥有 `ReplicatedStateMachine`、`PartitionStateMachineRegistry`、`StateMachineRecoveryCoordinator`；Order 和 Trade 只负责将自身二进制业务状态映射到这组公共接口，**不新增选主协议、分布式日志或 MD-to-MD 复制**。

本轮验证分支：`ha-common-state-machine-validation-20261011`。两服务都使用默认关闭的开关：

- Order: `order.cluster.stateMachine.commonBinding.enabled=false`。
- Trade: `trade.cluster.stateMachine.commonBinding.enabled=false`。

各自 Spring `OrderCommonStateMachineBinding` / `TradeCommonStateMachineBinding` 注入真实业务的 `snapshot/restore/apply` 依赖。已有分区生命周期工作线程根据 ZooKeeper assignment 调用 `reconcileAssignments`，为本机已分配的 Primary、Replica、Learner 建立**每分区一状态机**，失去 assignment 时注销。默认关闭，不能暗中启动恢复，不能绕过 `PartitionReadinessGuard`；这一步的注册不会执行 restore、切换 READY、晋升或归档 WAL。

## 已有真实 Journal 读入适配

**TradeCommittedLogSource** 使用真实 Chronicle Queue 读取 `STATE_BATCH / STATE_COMMIT`，采用每次最多 256 条的界限。只在两条的分区、epoch、sequence、eventId、commit payload 严格匹配、且整个 committed HEAD 经过外部授权时，才向 Common 输出业务 `apply(byte[])`；随后将提交标记作为占序号但不触发业务执行的 `protocolControl`。任何空缺、旧 epoch、伪造引用、未提交尾部或错位 marker 均 fail-closed。可用现有本地 `TradeCommitWatermark.scan` 证明本机持久提交 HEAD，但**这个本地证明不等于远端当前 Primary 权威身份的证明**。

**OrderCommittedLogSource** **不能**照搬 Trade 的相邻两条验证：Order 现有正式业务实现支持批量先写 N 条 `STATE_UPSERT/REMOVE`、随后写 N 个 `STATE_COMMIT`。因此 Order 使用原 `OrderCommitWatermark.scan(partition, head)` 对整个提交段累计校验；确认 `commitMarkerSeq == committedHead` 且所有 `STATE` 已提交后，再按物理顺序将 `STATE_*` 转为业务 `apply`；其他原始订单事件和提交/快照控制记录不触发状态机，但保留其日志序号。未知事件不得擅自重演撮合操作。日志错位、旧 epoch、未提交尾巴或改变 marker 引用都 fail-closed。

所有适配器都未接入真实远端网络层。注册和游标是**真实业务/真实本地日志集成**，但生产副本“权威新快照 → durable checkpoint → 原子业务恢复 → 远端 committed prefix → READY”仍需以下各项：

1. Common 的 `Control.requireSourceAttested` 由真正的当前 Primary ZK assignment/epoch、签名/可信通道、旧主 publisher fencing/CAS 实现。**本地 checksum 与 WAL watermarks 不可替代**。
2. `Control.persistVerifiedCheckpoint` 使用已 fsync 的完整镜像、正确的分区 baseline 和可恢复重试点；取代任何内存测试桩。
3. 获取贯穿整个恢复的分区独占屏障，复核真实分区归属；跨 epoch committed record 严格递增；延迟完成 `finishReplay`。
4. 恢复业务余额/持仓/挂单/去重，执行可审计的跨服务一致性校验后才授权 READY，失败保持 NOT_READY；无可靠源时不碰当前业务。
5. 两天日志回收必须由公共 `SnapshotRetentionFence` 以及消费者水位证明允许，不能仅凭文件日期删除仍需恢复的数据。
6. MD HA 仍沿 Order 权威全市场快照 + 连续增量来源，旧 publisher fencing、提升后全镜像、Robot 对账门禁未通过不能进行 SIGKILL 自动切主测试。

## 当前测试结果与发布

- Common `b5adf82`: 143/143 全量测试通过。
- Trade：原 237 项上新增真实 CQ 已提交游标 6 项、分区绑定 3 项；最新完整回归 **246/246**，零失败。
- Order：新增累计提交游标 5 项、分区绑定 3 项；**334 项全量回归，0 failed，0 errors，1 skipped**。验证分支最新 commit `714441e`。
- Trade：**246/246** 全量回归通过。验证分支最新 commit `4244b79`。
- Mac 开发期通过 `scripts/build-local-ha-demo.sh` 对 Common、com.app.dc、Order、Trade、MD 编译为唯一的 UTC build ID 本地版本，所有镜像 Common 二进制 SHA 一致；**不发布新版 Maven Central，不自动触发 GHCR 正式镜像，也不覆盖现网运行中的 Primary**。
- 本轮仅需推送 Order/Trade 的验证分支，`saas-crypto` 的默认发布流程保持不变，只有稳定后再将 Common 正式版及依赖一起合并发布。
- 基于精确 commit `Common b5adf82 / com.app.dc 2fa8047 / Order 714441e / Trade 4244b79 / MD bcdec88` 的本地镜像组 `~/.opentradingcore/local-ha-lifecycle-wal-20261011` **全部构建完成，三服务 Common JAR SHA-256 一致**：`96732b58ef3f33bb0ed9dcb42f30f3ca719bd7c0f1706501e50ac016a3aa4e12`；开发 Common GAV `3.0.17-devb5adf82220261011040356-SNAPSHOT`，镜像标签 `dc-saas/ordersvr:local-cb5adf822-20261011040356`、`dc-saas/tradesvr:local-cb5adf822-20261011040356`、`dc-saas/mdsvr:local-cb5adf822-20261011040356`。这是**Mac 开发验收镜像，不是正式生产 GHCR 镜像，也未替换正在运行的容器**。


## 已知性能边界

Trade 的 256 条批次 `readBatch` 仍是维护恢复路径，某些 Chronicle 队列跨度较大时底层依然可能重扫历史；后续可沿已有 Order `SequentialReader` 模式实现单次流式 tailer，避免长跨度日志 O(N²) 读放大。不应在单笔委托热路径启用恢复游标。系统当前不增加常态下单 TPS 的磁盘写操作。
