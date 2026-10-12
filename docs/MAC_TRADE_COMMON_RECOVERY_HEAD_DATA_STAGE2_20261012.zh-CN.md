# Trade Common 认证恢复 DATA/WAL 源端适配第二阶段（2026-10-12）

## 已提交的源码和构建证据

Trade repo: `bliplink/com.app.dc.tradesvr`
验证分支: `codex/trade-safe-wal-archive-canary-20261012`
HEAD 源端基线提交: `31f754abc4e6b2e8c0876c83ab9c6a9471f4eca9`
DATA + WAL 解码新增提交:
`897d524fe843ac85b0437a4848b371a2cb44e861`

- `TradeRecoverySourceHeadAuthority`：实现 Common
  `RecoverySourceHeadControlHandler.DurablePrimaryAuthority`，依当前
  精确 ZK assignment version、Primary READY、业务 mutation barrier、
  Chronicle 已提交 HEAD、合法 Full Snapshot SHA-256 签署源端声明所需水位。
  默认 `trade.cluster.recovery.source.enabled=false`，未发布网络入口。
- **重要语义修复**：Common 的 `RecoverySourceAttestation.SourceHead`
  `committedStateSeq/committedStateEpoch/commitMarkerSeq` 必须表示
  **源端最后累计提交水位**，不是早于最终 HEAD 的 Snapshot baseline。
  Snapshot baseline 由恢复请求 / Snapshot 文件单独提供。
  此问题在隔离的 `CommittedWalPrefixVerifier.requireComplete`
  测试中真实暴露并修复，否则存在合法 WAL 后缀被误拒的错误。
- `TradeRecoverySourceDataAdapter`：实现 Common
  `RecoverySourceDataControlHandler.SourceData`。
  每次读取先重新核对完整源端 HEAD；
  Snapshot 文件分块最大 64KiB，拒绝软链接、截断、
  越界及读取时文件代际变化；读取指定 WAL seq 使用
  Chronicle reader generation 锁和已归档多段安全读取路径，
  拒绝未经 HEAD 覆盖的尾部及单帧大于 Common 最大负载的记录。
- `TradeRecoveryWalDecoder`：把业务 Chronicle Queue 编码字节
  映射为 Common `CommittedWalPrefixVerifier.WireRecord`，
  核验 STATE_BATCH、STATE_COMMIT 事件类型、marker 版本、
  state seq/epoch/id，拒绝未来 marker。
  Common 校验器再证明整个 WAL 后缀累计提交、无 GAP、
  无非法 epoch 回退，不能只凭序号连续就发布 READY。
- `TradeSnapshotStore.sourceSnapshotFile`：经过分区名校验的只读
  Snapshot 源路径，拒绝 snapshot/file symlink。

Docker Maven Java 8 **Trade 全量测试 248/248 通过，零失败、零错误**；
新增源端 DATA 分块边界 / SHA / commit marker 相关隔离测试 15/15 通过。

本地候选镜像（已构建，**未替换在线业务容器**）：
`dc-saas/tradesvr:cluster-dev-local-c361e3e3d-20261012-headdata-897d524`
共同 jar SHA：
`0ed677b3c57bf65664c209c150570a598b1a9db7a82e63a694e1fe926bf003f3`
与前轮 Order/Trade-A 镜像所含 Common jar 完全相同。
本地镜像清单：
`~/.opentradingcore/local-ha-wal-seal-20261012-v1/artifacts/local-ha-images.env`。

## 完成情况和不可越过的发布门槛

这是**Trade Source HEAD / DATA 业务适配代码完成**，不是认证网络服务完成，
也不是 Replica Full Snapshot 自动同步完成。目前 `TradeReplicationManager`
只把普通 WAL `TradeReplicaReplicationHandler` 注册到
`DirectNettyReplicationServer`。禁止直接把
`TradeRecoverySourceDataAdapter` 注册为公开接口；
还必须实施：

1. Common HEAD/DATA 控制处理器的 operation 路由、
   物理节点独立强密钥、私有通道 ACL/TLS/mTLS 和 ZK 版本证明；
2. Source Snapshot **稳定文件代际**与分块下载期间的重传/失败隔离；
   避免每次 chunk 请求重算整个 18–19MiB Snapshot 的 SHA，
   可以使用经过验证的 immutable sealed snapshot generation；
3. Replica 端调用 `VerifiedRecoveryStagingClient` 完成签名
   HEAD + chunk/WAL 下载、SHA/WAL committed prefix 验证、
   fsync 后的 `DurableRecoverySnapshotSeal`；
4. 业务 Snapshot 通过 Common 的 `ReplicatedStateMachine.restore(ChunkReader)`
   等统一 StateMachine 入口在 **独占 Recovery/Writer 屏障**内安装，
   对 journal baseline/WAL/Projection 的变更必须可从进程故障恢复。
   任何不完整事务永不 READY；
5. 一个活跃租户做真实 B→A 角色反转 / 断主测试，
   对账持仓、资金、open order、成交、去重及 Projection；
   该项未过之前禁止替换尚承载活跃交易的 Trade-B。
6. 启用正常期 Common WAL auto-seal / auto-GC 仍是独立后续门禁；
   当前定时 Snapshot 继续运行，自动 WAL 删除关闭，Gateway 不修改。

仅 Common 和 Trade 的新开发源码/部署文档更新了独立 GitHub 验证分支，
没有更改在线容器或数据库，Demo 仍运行已验收的稳定镜像。
