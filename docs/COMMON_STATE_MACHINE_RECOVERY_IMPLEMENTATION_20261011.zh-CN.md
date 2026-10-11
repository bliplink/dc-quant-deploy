# 2026-10-11 Common HA 状态机恢复协调器：落地与安全边界

## 代码落地

Common `saas-crypto`：公共状态机 `ReplicatedStateMachine`、注册表 `PartitionStateMachineRegistry`、分块镜像 `StateMachineSnapshotStreams`，新增 `StateMachineRecoveryCoordinator`：
- `Control.markNotReady(partitionId)` **先于任何磁盘/业务写操作**调用；`withExclusiveBarrier` 必须由对应服务接到**真实的分区状态/leader/append 隔离锁**。Common 不擅自创建 ZooKeeper 主身份，不允许在未有屏障时标 READY。
- 恢复之前校验 SnapshotRecoveryBoundary、Primary 权威证明、完整 SHA-256、大小上限；业务仅收到通过验证的暂存文件字节流。
- `Control.persistVerifiedCheckpoint` 必须使完整快照和新的 journal baseline 可恢复且权威，不是把任何镜像 JSON 写盘就结束。
- `CommittedLogSource` 只能返回已经通过提交证明的增量；Common 检查 `seq=last+1`、epoch 单调不降、不得超过 `committedHeadSeq` / `committedHeadEpoch`，以及必须恰好抵达 committed HEAD。
- 只有恢复到 HEAD 并再次确认来源/权限后才能调用 `ReplicatedStateMachine.finishReplay()`（业务收尾：如 Order 延迟清理幂等信息）。整个 Common 恢复函数 **永不自动标 READY**；需要额外业务/持久化/旧发布者 fence 对账。
- 快照可为几十 MB；Common 使用 64KiB 流式 SHA-256，失败不调用业务 restore。分区持锁与固定内存上限保证不在每笔订单热路径扫描磁盘。

Common 源码：`src/main/java/com/app/common/replication/StateMachineRecoveryCoordinator.java`。测试覆盖连续已提交变更、跨 epoch 追平、同 epoch opt-in、源不权威、SHA 损坏、GAP、未注册分区、尾部缺失、失败不可 READY。

## 业务层最小接入

Order 工作树 `com.app.dc.ordersvr` 增加**待发布**的 `OrderBusinessStateMachine`：
- `apply(byte[])`：反序列化**提交后 STATE_MUTATION 数据**，调用已有 `OrderStateRecovery.applyRecovered(partitionId, mutation)`（按恢复模式观察订单幂等状态）。
- `snapshot(ChunkSink)`：复用已有 `OrderSnapshotManager.capturePartition`、`OrderPartitionSnapshotStore.streamSaved`，后者 64KiB 读取已保存镜像，不在 Common 再拼一个整个快照字节数组。
- `restore(ChunkSource)`：已有 JSON 业务快照经流解析后确认分区/version/books，再调用 `OrderSnapshotManager.restore`。
- `finishReplay()`：调用 `OrderStateRecovery.finishRecoveredReplay()` 延迟完成幂等清理。
- 这一类尚未通过 Spring 注册成为生产恢复状态机：**它在现有 Order RecoveryManager 执行链上仍是未启用的备用适配器**。进一步统一写入还需将 `OrderCommittedLogCursor` 严格映射为提交后的 STATE 事件并为控制类事件制定策略（不得把 CONTROL/CHECKPOINT bytes 当订单变更）。

Trade：已实现隔离的 `TradeBusinessStateMachine`，依赖 Common 的 `apply(byte[]) / snapshot(ChunkSink) / restore(ChunkSource)`；实际业务使用原有 `TradeRecoveryApplier` 的新路径 `restoreStateMachineSnapshot`、`applyStateMachineBatch`，不会在单次回调里调用 `markRecovered()`。还补了旧 epoch 快照前进恢复、残留持仓/去重清理、50MB+ 真实文件流 SHA 核对和 **固定 inode 文件句柄**：在分区锁下完成快照并打开文件，释放热锁后再按块传输，避免整段大文件 IO 阻塞交易。Common→Trade 端到端隔离验收已覆盖完整资金/持仓/去重恢复、控制日志跳过、后续状态变更、来源拒绝、NOT_READY。**尚未将适配器与真实 ZooKeeper 权威来源/持久 checkpoint/业务自动晋升运行时接线，不代表 Trade 生产 HA 自动恢复已经上线。**

MD：仍独立按 Order 权威**当前全市场镜像**恢复，不需要 MD ↔ MD 第二套日志复制，原有旧主发布 epoch fencing、Gateway publisher 过滤、Robot 对账门禁保持关闭自动晋升。

## Mac mini 本地验证与生产边界

- 依赖路径：本地 Common 开发 Maven GAV，不发布 Maven Central。所有 Order/Trade/MD 镜像必须使用同一 Common JAR SHA-256；正式 GHCR 镜像不受本地开发镜像覆盖。
- Common `b5adf82` 全量测试 **143/143 PASS**，包括 `finishReplay` 和 `CommittedRecord.protocolControl(epoch,seq)`；协议控制日志也占序号，不调用业务 `apply`，控制日志若制造 GAP 继续 fail-closed。只要后续有变更需复跑。
- Mac 构建根目录：`~/.opentradingcore/local-ha-sm2-20261011`；三个 linux/arm64 开发镜像均由同一 Common `3.0.17-deve28f0c00-SNAPSHOT` 构建成功，JAR SHA256 `e6f2ff29a3b394115d84fb21729a885b54e4062ee212e7e439e66fe94128d333`。
- 最新公共层测试：**Common 143/143；Trade `7c70e44` 的全量业务测试 237/237（0 fail / 0 errors）**。Order 上轮 326 tests / 0 fail / 1 skip，MD 上轮 125/125。对 `Common b5adf82` 本地镜像完成一致性构建，最终联合回归正在继续；不能把先前测试算作最终镜像的新验收。现网仍是原来的 Order/Trade Primary + 已验证 MD-C 本地金丝雀，未做故障注入，也未自动清理业务 WAL。
- Order 业务适配器保存在 Mac 本地 Git commit `e8b77a3`，**未推送 saas-crypto**，因为正式 CI 使用的 Common 3.0.17 尚无新接口，直接推送会使正式 GitHub Actions 构建失败。开发环境继续使用唯一 SHA 命名的 Common -dev-SNAPSHOT，符合稳定后再统一发布 Maven Central 的策略。
- Trade 业务适配器 Mac 本地 commit `32a4257`，业务集成及文件句柄测试 commit `7c70e44`，仍未推送正式服务分支。开发脚本 `scripts/build-local-ha-demo.sh` 从本轮开始对每个隔离镜像组使用 `3.0.17-dev<common-git-sha><UTC-build-id>-SNAPSHOT`，**同一次构建 3 个服务的 Common SHA 完全一致**，不同批次不会因为 Maven 打包时间戳而覆盖同一开发 GAV。稳定后再发布正式 Maven Central 与 GHCR。


## MD HA 现网预检查（只读）

2026-10-11 用 `scripts/check-md-failover-preflight.py` 再次核对 Mac 正常十租户环境：**256/256 分区 READY、MD-A 128 / MD-B 128 Primary，MD-C 有 ephemeral 连接、没有分区不就绪**。主站与 Trade 终端均 HTTP 200，磁盘约 65% 使用、154GiB 可用。MD-C 使用上一轮本地金丝雀镜像，Order/Trade、MD-A/B 仍运行稳定的 GHCR 旧镜像。业务没有重启或清理任何 WAL。

**阻断列表（决定性）：** `MD_NODE_UNHEALTHY_OR_UNREVIEWED:MDSvrC`、`ORDER_CURRENT_FULL_MARKET_IMAGE_PROOF_MISSING`、`MD_PROMOTION_FENCING_AND_CAS_CONTROLLER_NOT_CONFIGURED`、`MD_PROMOTED_EPOCH_FULL_MARKET_IMAGE_NOT_ATTESTED`、`ROBOT_POST_FAILOVER_ORDER_RECONCILIATION_NOT_ATTESTED`。预检查结果 `decision=BLOCKED`、`canInjectMdPrimaryFault=false`、`canPromote=false`。这些门禁不能为了 Demo 压测绕过；需要先实装相应的主身份 fencing、完整市场源端 attestation 和恢复对账，再做真实 SIGKILL 验收。

## 下一步门禁

1. Order/Trade 业务适配器和公共状态机接口的隔离测试已完成；**下一步是真正将其接入生产分区生命周期**：Spring Factory 注入、可信 `CommittedLogSource` 的 `STATE_BATCH` / protocol control 分类、快照阶段不可抢占、持久 checkpoint、真实 ZK fencing/独占屏障与 readiness 双重验收。业务存储操作和恢复状态不要在 Common 中另造逻辑。
2. 统一 Common `CommittedLogSource` 来源、主权威 HEAD、应用前后分区排他锁；无 GAP 才 READY。
3. 落实 2 天归档策略：可信 snapshot 覆盖 + 全部仍需补偿的消费者水位 + 文件关闭/无句柄 + 回滚证明，不能按日期直接删含业务 `.cq4`。
4. MD HA 在 Order 的全市场权威证明与旧主已停止发布、Gateway epoch fencing 就绪之前不能打开。优先用同版本镜像在 Demo 冷重建后验证 10 租户 Robot 持续运行，再故障注入。

这个文档是**代码已实现/待接入/现网状态**的区分，不代替正式 HA 故障注入报告。
