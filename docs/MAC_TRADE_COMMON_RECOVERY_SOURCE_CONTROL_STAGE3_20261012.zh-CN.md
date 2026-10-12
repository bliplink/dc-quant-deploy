# Trade HA Common SOURCE 控制路由第三阶段（2026-10-12）

## 本轮已完成

Trade repo `bliplink/com.app.dc.tradesvr`
验证分支 `codex/trade-safe-wal-archive-canary-20261012`
提交 `e39b868f989268d164f10b7c032f6271ffc1d84b`

基于此前完整的 `TradeRecoverySourceHeadAuthority` /
`TradeRecoverySourceDataAdapter` / `TradeRecoveryWalDecoder`，
已将 Common 的两个控制处理器装配到 Trade 原有的
`DirectNettyReplicationServer` **可选**控制口，不增加公共 HTTP、
Gateway 路由、额外业务服务、交易写热路径同步或日志 IO。

- `TradeRecoverySourceControlRouter` 接收 Common 两种恢复专用命令
  `RECOVERY_SOURCE_HEAD_V2` 和 `RECOVERY_READ_DATA_V2`，
  对其他操作返回 `UNSUPPORTED`。
- 必须有 `trade.cluster.recovery.source.enabled=true` **显式开门**；
  缺省为 false，旧 WAL 复制 handler 始终走原来的路径。
- 为避免在未具备 TLS/mTLS 的情况下将 18MiB 含业务数据的快照公开，
  **当前第一阶段强制 replication bindHost 为回环地址**
  `127.0.0.1 / ::1 / localhost`，拒绝 `0.0.0.0` 等公网绑定。
  这只是 Mac 单宿主机隔离要求，**不是跨主机正式发布的 TLS/mTLS 替代品**。
- 必须有独立物理节点的至少 256bit 十六进制密钥
  `trade.cluster.recovery.source.nodeKeyHex`；
  无密钥、格式不符或节点身份不匹配均 fail-closed；
  **现网未配置任何新密钥，也没有开启此功能**。
- `RecoverySourceHeadControlHandler` 签署新鲜的 ZK 版本 /
  Primary / committed HEAD；`RecoverySourceDataControlHandler` 验证
  客户端知晓物理节点的密钥，HEAD 前后版本一致，
  每个快照 chunk/WAL slot 各有密钥绑定的签名帧。
  Source 的业务读操作只读 Snapshot/WAL，不发布 READY。
- 已修正 HEAD `committedStateSeq/commitMarkerSeq` 为最终累计提交水位，
  Snapshot baseline 独立证明。否则真实 WAL 后缀会被错误拒绝。
  此协议语义由 `TradeRecoveryWalDecoderTest` 真实覆盖。

Trade Java8 Maven **全量 252/252 测试通过**。
`TradeRecoverySourceControlRouterTest`（4 项）覆盖
公网绑定拒绝、无密钥拒绝、非恢复操作拒绝、未认证请求拒绝。

本地镜像候选已打包但**未部署**：
`dc-saas/tradesvr:cluster-dev-local-c361e3e3d-20261012-source-control-e39b868`
Common JAR sha256 与正在运行的 Order 三节点一致：
`0ed677b3c57bf65664c209c150570a598b1a9db7a82e63a694e1fe926bf003f3`。

## 尚未完成的关键闭环（严禁直接开启新恢复服务）

1. **Replica 主动调度**：识别 Full Snapshot 滞后并向当前认证物理
   Primary 拉取新一代图片。当前 10 活跃分区快速恢复预检 10/10 BLOCK。
2. **Source 快照代际**：当前 HEAD/DATA 可重新哈希最新 Snapshot，
   但每个 chunk 都重新计算可能造成大量后台 IO；须先在
   immutable sealed snapshot generation 做索引固定和安全缓存，
   Source 数据与连续变化的权威 HEAD 需要正确交接。
3. **接收方安装**：`VerifiedRecoveryStagingClient` 的传输校验、
   `DurableRecoverySnapshotSeal`、`ReplicatedStateMachine.restore`、
   真实 Chronicle Journal Snapshot baseline/commit suffix 安装，
   以及断点中断事务对账，尚未在 Trade 服务接入。
4. **精确权限**：私有网络部署前必须完成独立密钥分发、TLS/mTLS、
   业务收发节点访问控制和对公网端口的拒绝。
5. **单分区故障试验**：B→A role reversal + kill/current epoch fencing；
   资金、持仓、去重、订单、成交、Projection committed watermark 逐项核对；
   过关后才允许替换 Trade-B，或开启自动 WAL 正常期物理封段。
6. 真实 WAL 自动删除仍关闭；`SnapshotRetentionFence` 是独立发布门禁。

该提交是**源端网络路由的默认关闭代码**，并不表示在线已经完成
Snapshot 复制 / HA 容灾 / WAL 自动归档上线。本轮未更改
Gateway 的任何业务代码或线上 Trade-B。
