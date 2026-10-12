# Trade-A 离线 Snapshot 温缓存与 ZooKeeper 短断恢复现场（2026-10-12）

> 此文档记录真正执行过的 Mac Demo 操作；不是正式 Trade 双向
> SIGKILL 验收。记录截至北京时间 18:01，后续状态以新的实机审计为准。

## 修正网络拓扑误判

实机 `docker inspect` 证实 **Trade-A、Trade-B 均为 Docker host 网络**，
并非独立 bridge 命名空间。应用配置是
`TradeSvrA=127.0.0.1:19221`，
`TradeSvrB=127.0.0.1:19222`，主机端口 TCP 均可连通。
Mac 同机 Demo 可以使用 loopback 私有认证传输；
真实跨主机版本仍需要加密与强密钥保护。
**Gateway 完全没有修改**。

## A/B 权威数据的独立只读核查

从两个挂载的 Chronicle Queue `.cq4` WAL 使用
`SingleChronicleQueueBuilder.single(dir).readOnly(true)`
读取，数据卷为 `:ro`，无任何业务写入。

第一项：所有十个活跃分区 Trade-A 与 Trade-B
最新 `STATE_COMMIT` 序号及 epoch 完全相同，
例如 P023 双方都是 `seq=284726 epoch=7`。

第二项：对 B 最新完整 Snapshot 的
`snapshotSeq`，在 A/B 两个物理日志中读取对应
`STATE_COMMIT` 原始编码内容，**十个分区均完全一致**，
同时 `STATE_COMMIT.stateSeq/stateEpoch` 与
Snapshot `committedStateSeq/committedStateEpoch` 相同：

| Partition | B full Snapshot seq | Epoch |
|---|---:|---:|
| P023 | 278678 | 7 |
| P054 | 286946 | 2 |
| P060 | 277908 | 2 |
| P077 | 274760 | 1 |
| P158 | 276424 | 2 |
| P160 | 282388 | 4 |
| P177 | 277832 | 1 |
| P201 | 273050 | 3 |
| P244 | 279602 | 2 |
| P246 | 277616 | 2 |

ZooKeeper 直接从
`/dc/cluster/tradesvr/partitions/Pxxx` 读取实际 assignment，
十个分区均为 TradeSvrB Primary + TradeSvrA Replica +
READY，epoch 与 Snapshot 相同。包括 2 个旧式
最小 Assignment JSON（P077、P177，没
`assignmentVersion` 字段）；严禁因解析器只接受现代
元数据而误报分区不存在。

## 已执行的受控安装

1. 将 B 最新完整 Snapshot 按原子代际读取到 Mac 的独立暂存目录，
   SHA-256 两次核对、fsync，文件总字节数 `193389858`；
   将 A 原来的 10 份快照逐项另存为可回滚副本。
2. 暂存和回滚：
   `~/.opentradingcore/local-ha-wal-seal-20261012-v1/artifacts/trade-a-offline-warm-20261012/`
   （`new/*.json`、`rollback/*.json`、
   `manifest.json`）。源端 B 10 份 SHA 在切换前仍相同。
3. 只对 A 执行 `docker stop --time=12 dc-saas-tradesvr`，
   确保 B 继续 Running。
4. A 停止后运行
   `~/.opentradingcore/local-ha-wal-seal-20261012-v1/artifacts/offline-trade-a-snapshot-install-20261012.py --apply`：
   每个分区在原目录内写临时文件、fsync、
   sha256 验证、atomic replace、目录 fsync、
   安装后的 sha256 验证；原文件版本与事先 SHA 不同则拒绝。
   执行中出错会回滚本轮已安装分区。
5. 10/10 安装成功并重新 `docker start dc-saas-tradesvr`。
   **没有停止或替换 Trade-B，也没有改它的镜像**。
   A 的镜像仍然是 `c361e3e3d-20261012034946`。
6. 完成后单纯比较全量 Snapshot 的预检从
   `blockedCount=10` 变成 `blockedCount=0`，但工具仍然正确地
   报告 `fastSnapshotPreflight=UNPROVEN`、
   `walAndReplicaAckProof=NOT_CHECKED`、
   `authorizesPrimaryRestart=false`，**因此没有 B SIGKILL**。
   B 后续恢复过程中产生新的 Snapshot Checkpoint，
   A 可能再次落后；不应把一次检查结果作为持续 HA 保障。

## 观察到的恢复性能事件（严重，不能掩盖）

17:53:49 左右，B 的共享 ZooKeeper 连接出现短暂
`Disconnected`，本机业务安全栅栏按设计阻止写入；
17:53:51 已 `SyncConnected`。日志中的客户端超时
`4435ms`，配置为 6000ms session timeout。
这和本次受控 A 停机操作在时间上接近，
**不能仅凭时间关联断言由 A 停止引发**；
需要关注 Docker VM 共享 CPU / GC / IO 调度卡顿。

由于对不可确认的业务分区拒绝 READY，B 按
`TradePartitionLifecycleManager` 逐分区重做权威状态恢复。
恢复期间 Robot 曾出现 DEGRADED/ERROR、委托下降。
17:55:01 P060 恢复 READY；
17:56:18 P077；
17:57:38 P201；
至 18:01:39，实时监控显示 **7/10 租户已恢复到
RUNNING + 40 active orders**。恢复监控 Job：
`wc_job_ILoYZ-auHcrVBIbF`，
轮次审计 JSON 在
`~/.opentradingcore/local-ha-wal-seal-20261012-v1/artifacts/trade-restore-tenant-poll-*.json`。
剩余分区继续恢复；此文档未将其伪报成全部通过。

B 曾对 dirty tail 采取 checkpoint 与
`TRADE_PARTITION_UNCOMMITTED_TAIL_ARCHIVED`，
没有证据能够替代权威状态 / MySQL / Projection 一致性对账，
因此 **B 和 WAL GC 都保持不动**。


## 恢复完成后的追加只读结果（18:05 及之后）

- 监控在 **18:05:04** 报告
  `TRADE_ALL_10_TENANTS_RESTORED`；
  后续独立审计再次
  `PASS_10_TENANT_SNAPSHOT`：十个租户全部
  Robot RUNNING，40 active orders，买卖盘口各 10 档。
  所有 Order/Trade/MD/Robot/Gateway 容器 Running，
  restartCount=0，OOMKilled=false。证据：
  `tenants-after-a-warm-all-recovered-final-20261012.json`。
- 在运行数据卷 `:ro` 下，用 Chronicle Queue
  backward tailer 从 A/B 各找最新
  `STATE_COMMIT`，**10/10 精确序号、epoch、
  原始编码内容相同**（例如 P023 双方 seq=287130 epoch=7）。
  此检验只能证明抽查时点的最新提交记录，不替代全量
  跨 MySQL/Position/Balances/Order 对账。
- B 完成恢复后，为其中 9 个分区创建了更新的完整 Snapshot
  Recovery Checkpoint，离线安装在 A 的较早 Snapshot
  **再次落后 9/10**，预检
  `blockedCount=9`、`fastSnapshotPreflight=BLOCK`、
  `authorizesPrimaryRestart=false`。证据：
  `trade-preflight-after-b-recovery-final-20261012.json`。
  **没有对 Trade-B 执行 SIGKILL 或替换镜像。**
- 新增离线温缓存助手脚本也存入
  `tests/trade-replica-offline-snapshot-warm-20261012.py`，
  默认 dry-run，只有显式 `--apply` 才执行；
  仅限 A 已停止且 B 运行，逐项 SHA 校验与 fsync，
  保存了本次可用的 rollback 文件。该一次性工具
  不能代替 Common 的认证自动温缓存。
- **新的 P0：Projection lag**。轻量查询显示
  `dc_trade_projection_watermark` 共有 10 条，
  但部分分区 MySQL committed journal_seq
  明显落后于当前已提交 Trade WAL。
  例如 P023 MySQL watermark seq=219475，
  当时 A/B 最近 STATE_COMMIT 已 >287000。
  Projection 日志多次出现
  `Projection realtime buffer reset ... GAP fetch remains authoritative`，
  不能据此推断它已经正确追平 archived WAL。
  **因此禁止 WAL 自动删除、禁止声称权威一致性完成。**
  下一步重点验收历史 Archive GAP 读取（Trade 分支此前补过
  `readTailRangeConcurrentReadOnly` archive handling），
  以及 Projection MySQL watermark 的持续前进与精确尾部对账。
- ZK 短断后的 Trade-B 从 17:55 到 18:05 才让十个活跃
  Robot 全部恢复，暴露恢复性能不足；后续应在独立故障
  演练环境优化**保守的会话再核验与快速 READY 恢复**，
  不能绕开 fencing 或强制提升。

## 后续准入

- 先确认再次 10/10 Robot RUNNING、活动委托完整，
  检查归档恢复后的 A/B 精确 WAL committed prefix，
  确认无双主和业务异常。
- 不能在当前未通过权威最终一致性检查的前提下，
  对 B 做 SIGKILL 或启动 200 租户新负载。
- 后续新版本 Trade 应通过 Common 签名 HEAD + Manifest
  自动温缓存，而非依赖人工离线复制。
- 优化 ZK 短断时冗长的串行分区重建，注意不能简单绕开
  epoch/role/barrier/commit 水位核验获得虚假 READY。
- 目前实际线上仍是原先 Order A/B/C 与旧 Trade A/B 镜像；
  Common `6b8fe7d` 和 Trade `8d0776e` 是已测试并构建但未滚动上线
  的验证分支和候选镜像。
