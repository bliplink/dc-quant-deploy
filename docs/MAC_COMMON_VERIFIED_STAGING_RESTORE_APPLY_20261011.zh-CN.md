# Common 接收 Staging → Restore → Apply → REPLAY_COMPLETE 安全验收（2026-10-11）

## 本轮执行范围

**最终 GitHub 版本：Common `7bdd352` 已推送 `saas-crypto`（以及 `codex/common-source-head-attestation-20261011`）；本轮无 Order/Trade 源码新增提交**，两者使用已有 `1c0014c` / `f3318d5` 验证分支完成新版 Common 兼容回归。部署仓库文档另行提交，不代表在线镜像已升级。

目标是**继续复用 Common 公共状态机机制**，让 Order/Trade 只负责解析真实业务 Snapshot/WAL；不得重新在 Order/Trade 内复制 Election/HA 机制。使用独立 Java 8 Maven 编译目录 `~/.opentradingcore/local-common-protocol-20261011/source/`，不动 Mac 10 租户运行环境、不换镜像、不清理 Archive。

### 实际完成的 Common 事务接线

- `VerifiedRecoveryStagingClient.stage` 继续从精确物理节点取得 Challenge-HMAC `SOURCE_HEAD_V2`，按最多 64KiB 的 `RECOVERY_READ_DATA_V2` 分块读取 Snapshot、按 WAL Seq 读取真实业务 CQ 记录，校验文件 SHA-256、帧 HMAC、顺序和累计 STATE/COMMIT，落盘 `image.bin`、`committed-wal.frames`、`VERIFIED_STAGING_NOT_READY`。
- 新增 `VerifiedRecoveryStagingClient.committedLogSource(...)`：生成正式 `StateMachineRecoveryCoordinator.CommittedLogSource`，对传输结束时 pin 住的整个 WAL 文件再次 SHA256、校验 Snapshot 原始 SHA、严格解析并在**任何 business apply() 前**重新执行 Common `CommittedWalPrefixVerifier`。然后将经过审计的 WAL 作为最多 4096 条、合计不超过 **64MiB** 的进程内不可变 `CommittedRecord` 游标提供给 `recover()`；STATE 转业务 byte[]，STATE_COMMIT 仅序号推进（`protocolControl()`），不重复应用到业务。
- `StateMachineRecoveryCoordinator.recover()` 改进次序：在 `NOT_READY + exclusive barrier + source attestation + Snapshot SHA` 之后先执行 `committedLog.open()` 全量校验，**再**执行 `DurableRecoveryTransactionControl.persistVerifiedCheckpoint()`（snapshot sealed、ledger INSTALLING、journal baseline fsync/attest、BASELINE_DURABLE）；避免损坏的 Stage 导致日志先被 destructive rebase。随后使用 sealed image `restore(ChunkSource)`、逐条 `apply(byte[])`、最终 re-attest、`finishReplay`、ledger `REPLAY_COMPLETE`。**没有 READY、没有 Promote、没有自动删除 Archive。**
- **修复公共数据模型的关键设计缺口**：旧 `RecoveryRequest.committedStateSeq/Epoch/Marker` 是「已包含在 Snapshot 的基线」且必须不超过 snapshotSeq，但 `RecoverySourceAttestation.SourceHead` 需要源端「最终的累积已提交 HEAD」——若增量中包含新成交，两者不能共享字段。本轮新增显式 `sourceCommittedStateSeq/Epoch/Marker` 及兼容构造器，`SourceHead.fromRequest` 按最终字段签署，`SnapshotRecoveryBoundary` 仍按基线字段严格拒绝回滚。旧构造方式继续兼容没有新增已提交 STATE 的恢复。新模型经过 SnapshotSeq=10、基线 stateSeq=8/marker9、最新 stateSeq=11/marker12、HEAD seq12 的实际 Netty→Snapshot/WAL→Restore/Apply 验证。

### 实际集成测试与故障安全

`VerifiedRecoveryStagingClientTest` 中使用本机真实 Netty TCP、二进制 Snapshot 分块、逐个 WAL 签名、隔离落盘、`PartitionStateMachineRegistry` 的业务注入、真实 `DurableRecoverySnapshotSeal` 和 `DurableRecoveryInstallLedger`，模拟源端校验由受控测试 Fixture 提供，不伪称在线 ZK 故障切换：

- 成功：业务 `restore()` 恢复二进制 Snapshot，`apply()` **恰好执行 1 次 STATE**、`STATE_COMMIT` 不再 Apply；成功写出 `REPLAY_COMPLETE`、`replayedCommittedSeq=12`，业务仍 NOT_READY，需外部资金/仓位/Projection/Fencing gate。
- 修改完成 Staging 后的 WAL 任意字节：再次 `committedLog.open()` 被 SHA 拒绝，重新执行 `recover()` 也在任何新业务 Apply/安装事务前失败，保持 NOT_READY，原 `REPLAY_COMPLETE` 记录未被篡改。
- 故意把 final committed State 水位当作 Snapshot baseline（stateSeq>snapshotSeq）：Common `SnapshotRecoveryBoundary` 正确拒绝，**没有为使测试变绿而放宽边界**；正式新构造器使用独立 Snapshot baseline/final HEAD 解决这个真实数据模型问题。
- `RecoverySourceAttestationTest` 与 `StateMachineRecoveryCoordinatorTest` 一起执行，针对旧源验证、恶意 epoch 与旧恢复操作保持向后兼容。Java8 **全量 Clean Maven 依赖链终态**：Common **199/199 PASS**；Order **336 tests，0 失败，1 skip**；Trade **240/240 PASS**。合计 **775 项，0 失败，1 跳过**。
- Full clean 初次暴露 **6 项旧 Frame 测试夹具错误**：旧夹具虚构 `STATE seq == COMMIT marker seq`；新安全模型拒绝。将这些仅用于签名/帧校验的测试夹具更正为有效 `state seq < marker seq <= snapshot seq`，**未取消任何错误帧或权限测试**，完整 Common 全量复跑通过。
- Common 专项实际 `Netty → SnapshotSeq10（stateSeq8/marker9）→ WAL stateSeq11/marker12 → Stage → checksum/cumulative Commit → fsync ledger/baseline → restore/apply → REPLAY_COMPLETE` **22/22 PASS**；事务结束仍 NOT_READY。损坏暂存 WAL 后再运行恢复，已验证阻断先于新的 journal baseline install，不会因此执行第二次业务 Apply。

### 架构边界：尚未完成、不能声称在线高可用接管

1. **没有真实业务副本的生产 Fencing/StateMachine 适配**：本轮用受控 Fixture 实施实际 Common Restore/Apply 和 ledger fsync，而不是在运行中的 Order/Trade replica 上调用。仍需由业务将合法 Snapshot 解码为资金/仓位/委托等内存态，注入真实状态机，并在实际 ZooKeeper Owner/Stat 版本下操作；Ledger.JournalBaseline 必须对真实 CQ 完成持久化复核。
2. **未完成外部 READY 验证**：Order/Trade 业务状态 + MySQL/Projection committed watermark + Gateway fencing + 无双主、无丢单/重复成交验收通过后才可以 READY。
3. **对恢复大尾部/重启持久化有显式限制**：本轮恢复源码审计最多 4096 WAL Slots、64 MiB。当前 Result 是**进程内 pin 的验证回执**，重启后不能直接根据纯文本 `VERIFIED_STAGING_NOT_READY` 恢复；必须重新从当前 Primary 鉴权取证或实现独立签名 manifest。Archive→Active 多段状态迁移仍需实现，不能使用自动 Archive 删除。
4. **网络隐私、性能**：虽然 Netty 数据控制端具备请求方 HMAC 身份证明，明文 TCP 还需 TLS/mTLS + 访问控制；目前源端在每次读取前后重验 Snapshot SHA/HEAD，在活动写入阶段会有昂贵计算和安全失败，需要不可变 Snapshot/WAL Pinning 后才可启用长时间恢复流；**所有新功能默认关闭**，对在线下单复制路径无新增处理。
5. **正式发布链**：Common 代码先进 `saas-crypto`，Order/Trade 仅独立验证分支。正式发布 Central 新 Common GAV → `com.app.dc` 引用新版本 → GHCR ARM64/Linux → Mac 单分区灰度测试；未经运行级安全验收不启用 `commonBinding.enabled`。
6. **MD 与日志 Archive**：MD 全市场权威状态、旧发布者 Fencing、RECOVERING→READY、Robot 对单仍为阻断项；Archive 保留安全 HOLD，直到真实归档→活动追平、完整水位和保留期证明。不得运行 MD 主切或自动删除归档以规避验收。

### 本轮结束后的真实 Mac Demo 核验

- `check-demo-tenants-readonly.py`：**PASS_10_TENANT_SNAPSHOT**，10/10 租户 Robot=RUNNING，每个 40 单，盘口各有 10 档双边深度。证据 `~/.opentradingcore/local-common-protocol-20261011/artifacts/after-recover-staging-transaction-10tenants.json`。
- `check-projection-consistency-host.sh`：Order/Trade `watermark_tail_mismatch=0`、`orphan_mutations=0`、`cross_partition_event_ids=0`。当前运行 **24 个** `dc-saas-` 容器。
- `verify-order-cluster-state-host.sh`：**256/256 READY、256/256 Snapshot 集合一致、0 Learner**；A 129 / C 127 Primary、B 256 同步副本。Order A/B/C 无 OOM、无重启，旧本地镜像未变。

**操作原则**：此轮未执行清空/重部署、未更新当前运行的正式服务镜像、未影响已有 10 租户 Demo，仅实现 Common 源码与独立测试。**源码测试通过 != Order/Trade 在线新恢复完成**；后续真实业务接线和故障注入仍需进行。
