# Trade Common Recovery HEAD 业务适配第一阶段（2026-10-12 15:00 CST）

## 本轮已确认现网

- Order A/B/C 三节点仍是 Common `361e3e3` 统一镜像，Trade-A 已替换 reader-generation 版本，Trade-B 仍为稳定旧版；MD/Gateway 未替换。
- Trade-B 是 10 个活跃交易分区的 Primary，Trade-A 是对应 WAL Replica。
- 10/10 Robot RUNNING、每租户 40 活动委托、盘口两侧 10 档。Trade-B 不能直接重启，因为副本最新 Full Snapshot 预检 **10/10 BLOCK**。
- 不修改 Gateway 业务透传，不动已开启的定时 Snapshot，不开启 WAL 自动删除/物理轮转。

## Trade 源码已提交并推送

Trade 验证分支：`codex/trade-safe-wal-archive-canary-20261012`
提交：`31f754abc4e6b2e8c0876c83ab9c6a9471f4eca9`

新 `TradeRecoverySourceHeadAuthority` 实现 Common
`RecoverySourceHeadControlHandler.DurablePrimaryAuthority`：

1. 默认 `trade.cluster.recovery.source.enabled=false`，不自动注册 Netty 恢复接口。
2. 必须具备 ZooKeeper 控制连接及当前精确版本的 Primary assignment；业务 partition 处于 READY 且没有 pending recovery。
3. 在与交易状态变更共用的 partition mutation barrier 中，核对本地 WAL committed marker、真实日志尾、Full Snapshot 基线 epoch/seq。
4. 读取完整快照到 SHA-256 **仅用 64 KiB 缓冲**，校验文件不是 symlink、读取前后文件属性未改变。
5. 重读 ZK assignment、epoch、HEAD 和 Snapshot identity，任何状态变化拒绝签署。
6. 提供与 Common 认证恢复 HEAD 匹配的 `SourceHead`，但**不发签名**，签名必须由未来受控业务 Netty handler 持有独立物理节点密钥执行。

`TradeSnapshotStore.sourceSnapshotFile` 提供只读快照文件定位及 symlink 审核。

新单测 `TradeRecoverySourceHeadAuthorityTest` 覆盖默认禁止、未来 epoch、未提交尾部、快照超前、分区错配、缺少哈希、不合法提交边界、软链接拒绝等。

**Trade 全量 Java8 Maven 测试：242/242 PASSED，0 失败、0 错误。**

本地构建候选镜像（**未部署**）：
`dc-saas/tradesvr:cluster-dev-local-c361e3e3d-20261012-headsource-31f754a`

源码 SHA：`31f754abc4e6b2e8c0876c83ab9c6a9471f4eca9`
Common jar SHA：
`0ed677b3c57bf65664c209c150570a598b1a9db7a82e63a694e1fe926bf003f3`，
与正在运行的 Order/Trade-A Common Jar 一致。

## 还缺少的正式 P0 接线

- 物理节点独立 256-bit+ 密钥、安全网络 ACL/加密连接；
- 在 Trade 现有 DirectNettyReplicationServer 中注册经过认证的
  `RecoverySourceHeadControlHandler` 与 `RecoverySourceDataControlHandler`，
  为 snapshot 文件提供**固定代际只读句柄**和对 committed WAL slots 的确切读取；
- 备节点 `VerifiedRecoveryStagingClient` 下载、验 SHA、fsync、seal，
  独占恢复锁下由业务 StateMachine 接口完成 snapshot/restore 和 WAL 前缀 replay；
- 备节点自动安装最新 Snapshot 的控制机制，确保不与复制 append、尾读、Projection 以及 ZK Primary 竞态；
- 以至少一个活跃分区做 Primary role reversal/SIGKILL 验收，
  资金、持仓、去重、成交、委托、Projection 水位全面一致；
- 过关后才能继续 Trade-B 镜像替换，再实现同 epoch 自动 WAL 物理封段。
  ARCHIVE_SEALED 也**不代表 WAL 可删除**；独立 `SnapshotRetentionFence` 仍是删除门禁。

本轮只是**正式 Trade 源端 HEAD 适配第一阶段**，没有编造完成的
DATA/Replica install / 自动快照追平功能，也没有新替换在线镜像。
