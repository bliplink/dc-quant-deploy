# Order / Trade 复制日志归档与回收机制检查（2026-10-11）

## 结论

**已有日志归档和归档历史重放，但尚没有经过生产级证明的自动安全 GC。** 不能把 `.archive` 存在等同于“所有较早 `.cq4` 都可删除”，也不能以日期、目录名、checkpoint 文件个数代替 commit/副本/Projection 水位。

本轮不修改运行中的 Order/Trade 容器、配置、快照与日志；禁止在直播十租户负载中按时间手工删除活动 CQ 文件。

## Mac mini 现网只读证据

- 当前唯一业务目录：`/Users/kong/.opentradingcore/dc-saas-runtime-clean-20261010`。
- Order A/B/C `journal/.archive` 分别 **128、128、256** 个目录，合计 **512 个，67,108,864 字节（64 MiB）**。全是 `P###-epoch0-seq0-...` 且每目录仅有一个 128KiB `metadata.cq4t`；**零个 `.cq4` 业务分段**。
- 这 512 个目录虽然只含空队列元数据，**正在运行的 Colima VM 进程仍对归档 `metadata.cq4t` 持有打开句柄**（`lsof +D` 只读检查确认）。不能在业务运行中假定已关闭 ChronicleQueue 或移除它们；保留 64MiB 远低于发生 mmap/虚拟机文件共享竞态的代价。本轮未删除。
- Order A/B/C 运行中的 `journal` 各约 1.8GiB；Trade A/B 各约 3.3GiB，属于**活动**日志目录而非上述旧归档。部分 CQ `.cq4` 的按日期分段也仍在活动目录里，不可按文件名日期推断可删除。数据库及日志目录另计。
- 当前磁盘已有 **约 163GiB 可用（约 63% 使用）**，无需为仅约 64MiB 归档进行高风险热删除。
- 现网 Order A/B/C 的 `order.cluster.snapshot.periodic.enabled=false`；Trade A/B 的 `trade.cluster.snapshot.periodic.enabled=false`。仅“支持快照”和“支持归档”不等于正在按周期轮转和安全裁剪。**不要未经容量/延迟基线就直接打开定时快照**，避免影响 10～200 租户性能。

## 源码链路核对

1. **Order**：`OrderPartitionJournal.rebaseInternal` 关闭本分区旧 CQ，把旧目录移到 `journal/.archive`，然后保存新的 baseline；`OrderProjectionCommittedReader` 能从归档桥接历史事件；`OrderPartitionJournal.archivedRollbackCommitMarker` 在精确的 rollback commit 证明下仍需从归档取记录。`OrderProjectionDispatcher.assertRetentionSafe` 在删前可验证 Projection 持久水位，但**未找到其接入一个完整的自动 GC/定时删除调用链**。这只是删前保护之一，不包括所有副本追平和历史分支检验。
2. **Trade**：`TradePartitionJournal.rebase` 归档旧分段，`archiveSegments` 可为追平回放重建历史连续区间；`TradeSnapshotScheduler` 提供按已提交变更节流的快照，但在现网为 **disabled**。本轮没有发现运行中的 `.archive` 目录，不能把 Trade 现役文件当作归档删除。
3. **MD**：派生行情从 Order 权威数据恢复，不需要另写 MD↔MD 复制 WAL。K线/成交归档另需基于对应消费者的有效存储/查询证明，不能和 Order 的状态 WAL 混为一谈。

## 安全回收门禁建议（全部证明齐全才允许删除有业务记录的归档）

1. 有来源已提交状态的**完整 snapshot + durable checkpoint**，而非仅拿目录时间戳或状态 READY。
2. 每个承载该分区的同步 Order/Trade 副本持久追平到删除边界，且当前不存在恢复中的 LEARNER/REPLICA 需要旧区间。
3. Order 的 Projection 已持久化/消费至该区间末尾，且所有跨 epoch baseline/rollback 精确证据不依赖这份归档；Trade 自身的恢复区间也可由较新可信 snapshot 覆盖。
4. 保留足够宽的恢复/审计窗口，并用独立隔离实例完成**删除候选文件后的恢复演练**。
5. GC 使用独占文件/租约边界，操作前校验文件路径、打开句柄、稳定性、大小、SHA 与 manifest；**现役 CQ、当前 `.archive` 下还被 VM/Chronicle 映射的 metadata、MySQL/ClickHouse/日志恢复文件不删**。失败即保留。
6. 先观测容量及租户下单延迟，再让节流的 snapshot 轮转定期运行；GC 只处理已有最终一致性证明的候选，不在撮合热路径扫描或同步 IO。

## 本轮工具与测试

- `scripts/audit-order-archive-retention.py` 保持 `READ_ONLY_NO_DELETE`，新增 `metadataOnlyBootstrapArchives`、`archivesWithDataSegments` 及每归档 `retentionClass`。即使是 metadata-only，`deletionAuthorized=false`，明确标示活跃 VM 文件句柄与未证明的恢复/Projection 门禁。
- `tests/test_order_archive_retention.py` 新增空初始化 archive 分类、同名归档含 CQ 业务数据的拒绝误判测试，**9/9 PASS**。
- 现网 audit：512 个 metadata-only，0 个有业务 `.cq4` 的归档；安全结论 **HOLD：不删活跃 VM 仍打开的文件**。该结论不会因用户允许删除历史备份而变成自动删除许可。

**操作决策：** 保留正在被 VM 打开的 64 MiB 元数据；先把低开销的周期快照、真实副本/Projection 持久水位与离线恢复验收串成严格 GC 机制。磁盘已经安全（约 63% 使用），不需要冒险在线删文件。
