# Trade 副本恢复阻断：Snapshot/WAL 不同一世代（2026-10-14）

## 实际现场

只读读取正在运行的 Trade A/B 最近约 4 MiB 日志和每个被报错分区的 Snapshot **头部元数据**、WAL baseline.properties，不读取或输出资金/账户内容。

- Trade-A：8 个报错分区，P021、P042、P100、P134、P143、P200、P236、P246。
- Trade-B：P071；Snapshot seq=312034、localLastSeq（最近故障日志报告）=309369，持久 baselineSeq=309368。**这不是单靠调重试间隔能解决的情况**。
- 09:20 左右持续存在 `TRADE_REPLICA_WARM_RETRY phase:signed-head-manifest reason:IOException`，部分查询返回 `PARTITION_NOT_READY`。Trade 服务仍是 RUNNING，这不表示它所有分区已 READY。
- Trade-B 恢复暂存及 sealed 目录合计约 23GiB。目前无法证明安全回收，不应删除。

## 严格限制

日志中的 localLastSeq 是**最近故障诊断时观察到的值，不是一个新的、独立读取的持久 WAL HEAD**；审计脚本不会根据它授权恢复、主切、封存或删除。没有最新源端提交、ZK owner/CAS、Replica 水位证据时，现有 TradeRecoveryPlanner 拒绝快照超前是正确的。

运行中 Trade 镜像含有独立本地工作区的恢复/预热新源码，GitHub 的 `saas-crypto` Trade 分支目前不等价于运行镜像，不能直接用该分支覆盖现网 Trade A/B。

## 复现脚本

`scripts/audit-trade-recovery-cursors.py` 只读扫描最近日志和小于 4KiB 的 Snapshot 头部，不触碰完整交易数据。若发现无法解释的超前水位返回 BLOCKED，生成 JSON 报告，不执行任何修复。

下一步顺序：确认每个分区的权威 Primary 和持久提交 HEAD → 校验完整 Snapshot + WAL（含封存日志）是否能追平 → 通过 Common 已有恢复门禁进行隔离式安全安装 → 比对业务资金/持仓、Projection 水位 → 完成后以不可逆恢复会话标记为界安全退休旧暂存数据。不能通过文件日期或简单 rm 强制清理。
