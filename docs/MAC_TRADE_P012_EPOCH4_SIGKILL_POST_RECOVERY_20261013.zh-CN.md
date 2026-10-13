# Mac Demo：Trade P012 SIGKILL 后 Epoch 4 副本恢复复核（2026-10-13）

> 本文件记录实机只读验收及已发生的受控故障注入，不代表生产环境或 200 租户 HA/容量验收通过。集群为 Mac mini/Colima 单机 Docker VM。该测试仅为 Demo，未启用 TLS，未改 Gateway 纯透传代码。

## 镜像与部署

- **24/24** `dc-saas` 容器处于 Running 状态。
- Trade A/B 均使用独立本地 arm64 候选镜像
  `dc-saas/tradesvr:cluster-dev-local-c6b8fe7d-20261013-firstsnap-e249f74`。
- Trade 源码提交 `e249f74ddae882c0a4c530c87193144d1b5c663f` 在
  `bliplink/com.app.dc.tradesvr` 的
  `codex/trade-safe-wal-archive-canary-20261012` 验证分支；
  尚非正式 `saas-crypto` GHCR 多架构发布。
- 采用 `com.app.dc` 本地验证依赖
  `0.0.4-dev6b8fe7d20261012-SNAPSHOT`，Common JAR SHA256
  `34a6ee05db748eb2990f68b1dc86188a41ca52c320e1838b9cd82fd3c77a0363`。
  对应 Java 8 全量测试 **295/295 通过**。
- 清理旧 Demo 前已经保留 P246 独立证据。旧运行数据进入隔离目录，没有直接永久删除。

## 已发生的真实 HA 验收

- 先在 P200 进行 A→B→A 单分区受控角色反转，双向 READY、Projection 水位均 PASS。
- 新建第 11 个独立故障租户 `QGM88N`，在真实 API 下开仓并核对 MySQL 执行及
  **0.0001 BTC 多仓**。P012 初次 Snapshot 复制同 Epoch 1、seq 118。
- 第一次“持仓反转+SIGKILL”复合脚本因子脚本未继承私有 `ENV_FILE`
  提前退出，**该次未触发 SIGKILL**；独立验证工具使用显式 ENV_FILE 后，
  P012 的 A→B→A 受控角色反转 PASS，Projection 22 个基准水位持续不回退。
- P012 获得新代际 Epoch 3 的完整 A/B Snapshot seq 434，且只读门禁校验通过；
  随后实际对 Trade A 发出 `SIGKILL`，Trade B **自动接管至 Epoch 4**，
  出现 `TRADE_PARTITION_READY ... epoch:4`，MySQL 持仓未变化。
- 故障节点 Trade A 已重新启动，镜像和自动重启策略恢复。
  运行日志显示 Trade B 曾出现
  `TRADE_REPLICA_DEGRADED partition:P012 ... seq:507`，约 6 秒后出现
  `TRADE_REPLICA_RECOVERED partition:P012 seq:676`。
- Trade A 成功安装来自 Trade B 的 Epoch 4 可信快照，
  包括 seq 950 及后续 seq 3152。
- **最新只读证据**：ZooKeeper P012
  `primary=TradeSvrB`、
  `replica=TradeSvrA`、
  `state=READY`、
  `epoch=4`、
  `assignmentVersion=4`。
  Trade A/B 的 P012 完整 Snapshot 均为 epoch=4、
  snapshotSeq=3152、committedStateSeq=3151，**SHA256 一致**。

> 限制：同 Epoch 完整 Snapshot 相同和 `TRADE_REPLICA_RECOVERED` 日志
> 是强恢复证据，但**尚未独立认证“当前 WAL committed HEAD / 每条持久 ACK”**；
> 上述数据不能自动作为下一次 SIGKILL、滚动重启或 GC 的充分授权。

## 实时多租户与 Projection 只读证据

- 2026-10-13 再次只读审计 11/11 租户 Robot 为 RUNNING，每户 40 笔
  活动报价委托、盘口双边各 10 档；合计 440 笔活动 Robot 委托目标。
  脚本结果字符串为历史固定名称 `PASS_10_TENANT_SNAPSHOT`，
  此次 `expectedTenants=11`、`observedTenants=11`。
- Projection 孤儿 Mutation 0（分批 live 范围观察，**非事务权威证明**）；
  Trade/Order Projection 各 11 条水位，尾部不匹配 0，
  跨分区 Event ID 冲突未发现。
- Trade live Snapshot 门禁读取 256 分区 ZK assignment 和 11 租户：
  `snapshotBlocked=0`，但
  `walCommittedHeadAndAckProof=NOT_CHECKED`，
  返回 `snapshotPreflight=UNPROVEN`、`decision=BLOCKED`；
  **禁止解释为已获滚动重启/进一步破坏性故障授权**。
- 已严格只读核查 Order 三节点 256/256 assignments、
  `snapshot_sets_equal=256`，没有 Learner、容器重启或 OOM；
  未提供认证会话时跳过逐分区 HTTP 认证路由扫描。
- 测试租户 QGM88N 的测试交易员经**只读 SQL**再次核查：
  `long_position=0.000100000`、
  `short_position=0`。因执行环境拦截读取私有恢复登录凭据，
  **尚未按 API 平仓**。不能直接修改数据库、不能重复下单或声称已清理。

## WAL 归档 / GC 与性能

- 最新只读物理磁盘清单：
  - 活跃 WAL 已分配 `931061760` 字节（约 888 MiB）；
  - archive 已分配 `79253504` 字节（约 75.6 MiB）；
  - 归档目录 516 个：Order A/B/C 分别 128/128/256 个，Trade B 4 个，
    Trade A 0 个。
  - 超过 48h 保留阈值的候选目录 = 0；
    `deletionAuthorized=0`，未知/异常目录 0。
- 真实归档文件存在，但**仅凭文件数量不能证明自动归档调度持续正常**。
- 复查 Trade 源码 `TradePartitionJournal.rebaseInternal()` 可见 `.archive` 目录是在 **认证快照重基线/rebase 时关闭旧 Chronicle Queue 并搬移目录**后生成。`TradeSnapshotScheduler` 是独立定时**生成 Snapshot**，不是 WAL 定期归档任务。因此 Trade B 的 4 个 archive 目录是归档文件存在的证据，**不能说 Trade 定时自动 WAL 归档已经开启或正在周期运行**。
  WAL GC 未通过归档 Seal ledger、快照边界、Replica/Projection 水位
  和 Chronicle Reader generation 等安全门禁，**必须继续关闭自动物理删除**。
- 归档与 GC fail-closed 单元测试：`test_archive_retention_gc_canary.py` 6/6
  以及 `test_audit_saas_wal_archives_readonly.py` 3/3 均通过。
- 11 租户资源基线：
  CPU PSI(10s) = `9.57%`，
  Robot CPU 配额使用率 `11.31%`，
  Order B 内存配额使用率 `23.52%`，
  Order B 3s full GC = 0。
  `nextRampAuthorized=false`；2.40667 market rows/sec **不是 Order TPS**。

## 本地证据路径

位于 `~/.opentradingcore/local-ha-clean-20261012-v1/`：
- `held-sigkill-evidence/trade-sigkill-20261012T233731Z.json`
- `held-sigkill-evidence/20261013-073551-trade-role-reversal/`
- `trade-11-snapshot-gate-20261013.json`
- `tenants-epochwarm-11-20261013-next.json`
- `wal-archive-audit-20261013-next.json`
- `tenant-ramp-11-20261013-next.json`
- `tenant-epochwarm-held-sigkill-11.log`
- `held-sigkill-evidence/trade-held-20261013073236DBAC.recovery.json`
  （**0600 私有恢复凭据，不应上传/打印**）。

## 后续准入门禁

1. 不复制、不打印私有恢复凭据，通过被允许的 API 登录路径闭环平仓 QGM88N。
2. 追加可信的当前 Epoch committed WAL HEAD、Replica ACK、完整 Replica 可恢复性独立交叉证明，再决定是否继续 Order/Trade 故障注入或滚动更新。
3. 确认 Archive Seal 与持久 ledger/保留期/消费者持久水位/Reader generation
   全部可验证后，在独立 canary 开启受控归档退休；不得为追求节省磁盘绕过任一门禁。
4. MD C 的 epoch-fence 以及 MD 自动主切仍须单独验证；后续是 10 户 Soak，
   再 50→100→200 租户阶梯压力测试。不要把负载基线当容量结论。
