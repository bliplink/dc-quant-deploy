# Mac Demo：Trade Chronicle Queue 读者代际保护与 WAL 归档接线进度（2026-10-12）

## 本轮已提交的源码

仓库：`bliplink/com.app.dc.tradesvr`
分支：`codex/trade-safe-wal-archive-canary-20261012`
提交：`787a211`（`fix(trade-ha): pin Chronicle reader generation during journal rebase`）

核心文件：
`src/main/java/com/app/dc/service/cluster/TradePartitionJournal.java`

新增：
`src/test/java/com/app/dc/service/cluster/TradePartitionJournalReaderGenerationTest.java`

根因：Trade 的 replica catch-up / Projection 只读扫描取到
`PartitionState.queue` 之后释放了分区 append monitor，在扫描与回调期间
仍使用旧 Chronicle Queue，而 `rebaseInternal` 可以并发 `close()`
并移动旧目录，造成 mmap / tailer 生命周期冲突。

方案：

- 按 Partition 增加可重入的公平读写锁，异步读者在**整段读取生命周期**
  持有读租约，`rebaseInternal` 和 `close()` 要独占写锁才能关闭旧 queue。
- 所有正常 append/replica append 保留现有原子 seq + 分区 monitor，
  **不增加 Order/Trade 撮合热路径的 IO、目录扫描和读写锁开销**。
- 读取归档和当前 WAL 的路径共享同一个读租约；
  并在关闭后禁止创建新 PartitionState，保护旧/新 queue 代际。
- 完整提交证明仍依赖 Common 验证分支的
  `JournalArchiveRotationPolicy`、`DurableJournalArchiveSealLedger`
  与 `JournalArchiveSealCoordinator`，不能仅凭代际锁开启自动物理封段。

### 验证证据与阻断

- 修改初版通过 Docker Java8 Maven **8/8 针对性测试**，
  包括旧 Queue 读取中 `rebase` 必须等待、业务 append 不受慢读者阻塞、
  `close()` 必须等待 reader 释放、多个归档段追平以及 Projection 历史补缺。
- 随后增加关闭后的状态校验和锁对象复用（细微加固）后，
  **WebCodex 的全量 Maven 测试操作被安全检查拦截**，因此未获得
  本提交版本的全量测试证据。不能宣传 231+ 全量测试通过，
  不可直接发布镜像或灰度自动物理封段。
- GitHub 验证分支已真实推送；未合并 `saas-crypto`
  的正式 Trade 业务代码、未发布 GHCR/Maven Central、未替换现网镜像。

## Mac Demo 现场只读复核

本轮开发后（线上仍是原稳定镜像）：

- `tests/verify-order-cluster-state-host.sh` **PASS**：
  Order **256/256 READY**、`snapshot_sets_equal=256`、无 learner、
  Order A/C 为 Primary、B 持有全部 replica。
- `tests/check-demo-tenants-readonly.py` **PASS**：
  10/10 Robot RUNNING，每租户 40 活动委托，双边各 10 档；
  `tenants-trade-reader-fence-post-headroom-20261012.json` 为 Mac 私有证据。
- Order A/B/C、Trade A/B、Robot 均正常运行，
  没有新增自动重启 / OOM。Gateway 没有任何改动。
- Trade-B 的 `memory.current` 约 2.0 GiB（接近原 2 GiB 上限），
  其中匿名内存约 872 MiB、文件缓存约 1.13 GiB，
  `memory.events.max` 累计约 14852，`oom_kill=0`。
  为缓解 Chronicle 文件缓存回收压力，将 Demo 的
  `TRADESVR_B_MEMORY_LIMIT` **2048m → 2560m**
  （仅容器内存上限，JVM 堆未调整、未重启），并同步 Mac 私有
  `local-ha-runtime.env` / 权限 0600 回滚文件。
  提升后再次检查 10/10 PASS，Trade-B 约
  **1.838 GiB / 2.5 GiB**。这不是内存优化完成或 TPS 验收通过。

## 剩余开发门禁

1. 在 Common 验证事务内接入实际 Order/Trade
   `Adapter.acquireExclusiveBarrier/verifyLocked/switchWriterAndArchive`
   与 durable archive manifest，确保经授权的同 epoch 完整提交 HEAD
   才执行物理封段。
2. Order 的原始 Replica `readBatch` 仍只读活跃 WAL，
   必须补齐跨 archive 追平 / 已验证的完整 Snapshot 安装。
3. 隔离目录真实 Chronicle Queue 多轮封段，
   每一步 SIGKILL 恢复、历史 GAP、资金/持仓/订单一致性；
   并补跑 Trade 最新提交全量单测。
4. 对照 TPS/P99、CPU/IO、Docker 文件缓存压力后，
   才可灰度开启正常期 WAL 自动封段；
   **真实 WAL 自动删除继续关闭**，必须另过
   `SnapshotRetentionFence` 与 Projection/Replica 持久水位。

本轮没有运行新的物理封段控制器，也没有改动 Gateway。
