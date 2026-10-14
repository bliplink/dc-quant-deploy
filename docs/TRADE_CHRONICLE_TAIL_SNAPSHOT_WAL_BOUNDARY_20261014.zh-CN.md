# Trade Chronicle WAL / Snapshot 恢复边界验收（2026-10-14）

## 定位

Mac mini Demo 运行在 `saas-crypto`，Order-C 已使用 Common 3.0.20 / MySQL JDBC8 候选镜像；Order-A/B、Trade-A/B 尚未滚动，Gateway 保持纯透传。

Trade-A/B 存在 9 个业务分区无法恢复 READY，Robot 2 RUNNING / 9 ERROR (`RUNTIME_FAILURE`, `queryTradePosition: PARTITION_NOT_READY`)。ZooKeeper 分区 READY 不代表业务进程完成了提交恢复。

| 节点 | 分区 | 原运行时尾部 | 修复后真实可读 CQ 尾部 | 最新 Snapshot | 剩余序号差 |
|---|---|---:|---:|---:|---:|
| Trade-A | P021 | 279599 | 280940 | 280964 | 24 |
| Trade-A | P042 | 271107 | 272492 | 272528 | 36 |
| Trade-A | P100 | 283923 | 286014 | 286038 | 24 |
| Trade-A | P134 | 263817 | 266608 | 266638 | 30 |
| Trade-A | P143 | 276373 | 279112 | 279124 | 12 |
| Trade-A | P200 | 282051 | 284052 | 284088 | 36 |
| Trade-A | P236 | 268905 | 270494 | 270530 | 36 |
| Trade-A | P246 | 273163 | 275740 | 275944 | 204 |
| Trade-B | P071 | 309369 | 311962 | 312034 | 72 |

原 `snapshotSeq - runtimeLastSeq` 共 **19,581**，其中 **19,107** 序号经官方 Chronicle Java Tailer 的只读隔离验证可以从物理文件连续解析；剩余 **474** 序号在 A/B 两侧均未找到到达最新 Snapshot 的原始 WAL 尾部。**这里的序号并不等于已认证的提交条数或数据丢失笔数。**

## 确认的 Chronicle 缺陷

1. `ChronicleQueue.lastIndex()` 在真实 P200/P071 恢复样本中停在第一条物理记录，不能把它当最终序号。隔离数据上正向 Tailer 分别能解码 2,002 / 2,594 条连续记录。
2. `ExcerptTailer.direction(BACKWARD).toEnd()` 同样受过期索引影响：P200 `readTail(4)` 原返回序号 282051 的一条；真实末尾应是 284052、284051、284050、284049。
3. 已在 Trade PR #8 修复：启动时从 Chronicle hint 顺序读取至真实物理尾部并缓存其 **Chronicle 物理索引**，append/appendReplicated 更新索引，倒序读取 `moveToIndex(realIndex)`；序号不连续即拒绝恢复。恢复初始化扫描一次，交易追加热路径不做全量扫描。

## Snapshot 写前 WAL 同步屏障

原 `TradeSnapshotStore` 对 `latest.json.tmp` 调用 `FileDescriptor.sync()` 并同步目录，而 Journal `writeText()`、Replica ACK 未显式保证其对应 WAL 到盘。故 Snapshot 可能与 WAL 形成不一致的落盘顺序。

已在 Trade PR #8 增加 `TradePartitionJournal.syncJournalThrough(partition, requiredSeq)`，于普通 Snapshot 与恢复 Checkpoint **落盘前**在分区变更锁下调用。它校验序号边界，按已认证物理索引取得 Chronicle `DocumentContext`，并对所在 `MappedBytesStore` 执行 `syncUpTo(..., SyncMode.SYNC)`。源端 ACK/commit 判定仍独立于此屏障，绝不能把 msync 成功等价为源端提交证明。

**注意**：不能从 Snapshot 调度线程新取得的 `ExcerptAppender` 读取 WAL 最后写入位置。实际隔离验证：该线程的 `writePosition=66680`，真实写入线程为 `66728`；使用真实物理索引取得的 `DocumentContext` 映射才是正确同步起点。

真实隔离 WAL 副本 P200、P071 各完成一次边界 `msync`，耗时均约 **4 ms**（仅两次样本，非吞吐或磁盘失效性能证明）。正常每笔订单的 append/replicate 热路径未因 Snapshot 同步屏障新增 fsync。

## 代码与测试

- Trade 修复 PR：[bliplink/com.app.dc.tradesvr#8](https://github.com/bliplink/com.app.dc.tradesvr/pull/8)（**Draft，未部署**）
- P0：[bliplink/com.app.dc.tradesvr#7](https://github.com/bliplink/com.app.dc.tradesvr/issues/7)
- 隔离审计工具 PR：[bliplink/dc-quant-deploy#21](https://github.com/bliplink/dc-quant-deploy/pull/21)
- 最新 CI：[Trade validate Chronicle tail run 38520771469](https://github.com/bliplink/com.app.dc.tradesvr/actions/runs/38520771469)；包含后续 Snapshot msync 提交的 CI 以 PR #8 最新 Checks 为准。
- 本地 Java 8 Maven 全量：**231 tests, 0 failures, 0 errors**。
- 只读审计：`python3 tests/trade_snapshot_wal_forensics.py --data-root <offline-or-live-readonly-data> --log-root <log> --scan-cq-markers`，固定 `recoveryAuthorized=false`。
- 官方 Chronicle 物理索引、倒序和 msync 工具位于 `tests/TradeChronicleTailProbe.java`、`tests/TradeChronicleBackwardIndexProbe.java`、`tests/TradeJournalReadTailProbe.java`、`tests/TradeChronicleSyncProbe.java`。**会以 writable 模式打开队列的 Java probe 必须仅针对隔离拷贝运行**，绝不可指向直播分区。

## 尚未解决，严禁强行放行

- 剩余 **474** 个序号是否真正获得权威 committed-HEAD / quorum durable ACK 证明尚未认证。当前 A/B 原始 WAL 均未到达对应快照最新序号。
- Replica `appendReplicated()` 后的 ACK 目前没有单独的 crash-safe WAL 同步证明；**Snapshot 写前同步不能代替复制 ACK 的持久化保证**。后续需在 Common 统一复制协议中给出写入、提交、快照 HEAD 认证边界以及高性能 group-commit 或选择性持久化策略。
- Common 源端可认证 HEAD + 完整 Snapshot(byte[]) / Diff(byte[]) 的业务安装、原子回滚与 epoch fence 尚待贯通 Trade/Order；不能仅凭 snapshot 文件与 ZK READY 执行 forward rebase。
- 严禁删除归档、手动标记 READY、跳过缺口、修改 Gateway、直接替换当前 Trade Primary；先完成可信源端恢复，验收 MySQL/Projection/Order/Trade 对账、9 个 Robot 恢复，再做主备互换和故障注入。
- 当前宿主磁盘约 94% 使用，Trade 两份 Journal 共约 15 GiB，日志目录约 5 GiB；归档删除必须有 HEAD、Snapshot、Replica、Projection 消费水位证明。不能因占用高就盲目 prune。

## 验收门槛

1. Common 具备认证 HEAD、持续 WAL ACK、Snapshot/Diff 业务状态安装和可靠 fence，并证明退出/崩溃后的可恢复提交前缀。
2. Trade 9 分区在相同提交证明下可重启 READY，账本、仓位、余额、执行去重一致；Robot 11/11 RUNNING。
3. Order/Trade 共用机制下，通过真实 SIGKILL、追平、角色反转、归档删除与快照恢复；证明无双主、无丢单、无重复成交。
4. 验收前继续 **NO-GO**；CI 构建成功不等于现网恢复或发布成功。
