# Mac Demo WAL 封段事务阶段验收（2026-10-12）

## 本轮实现和提交

在 `bliplink/com.app.common` 的独立验证分支
`codex/common-wal-rotation-policy-20261012` 上，在已有
`JournalArchiveRotationPolicy`（提交 `bf6415b`）基础上，
新增公共持久化 WAL 封段事务：

- `DurableJournalArchiveSealLedger`：
  每分区 PREPARED → WRITER_SWITCHED → ARCHIVE_SEALED；
  文件写入通过临时文件、FileChannel.force(true)、原子 rename、
  父目录 fsync 持久化，校验 identity/hash、阶段、epoch、归档 seq
  单调递增；文件损坏、符号链接、未完成事务均 fail-closed。
- `JournalArchiveSealCoordinator`：
  后台预检、申请业务独占 writer/recovery barrier、
  屏障内重新核对权威 Primary、epoch、HEAD、Replica、Snapshot；
  再保存 PREPARED、调用业务适配器的物理封段、
  校验新 writer 基线、保存 WRITER_SWITCHED、
  校验历史归档可读、保存 ARCHIVE_SEALED。
- 仅在 Common 内部用于候选规划的 `preflight`，
  **不是授权**；真正的 `evaluate` 必须具有独占屏障，
  不允许先检查后在状态已变化时直接封段。
- `SnapshotRetentionFence` 仍是**独立的 WAL 删除证明**。
  `ARCHIVE_SEALED` 从来不代表旧日志已经能安全删除。

Common 验证分支提交：
`361e3e3d89c2b2120283485b32a76c6df6f1962d`
（`feat(common-ha): persist fail-closed WAL seal phases and SIGKILL recovery markers`）。

## 测试与复核

`docker run maven:3.8.8-eclipse-temurin-8 mvn -q -o test`
**228/228 全量测试通过，无失败/错误**。

新增覆盖：
- 文件系统阶段顺序、身份不符/损坏/软链接拒绝、跨归档 seq 的单调性；
- 物理切换 / 新 writer 验证 / 归档验证 3 个阶段错误注入；
- 独立 Java 子进程在三个已 fsync 的阶段执行强制终止，
  父进程读取持久化标记，重启后未完成阶段禁止继续；
- 在独占屏障内发现 HEAD 已变化时拒绝创建封段标记；
- segment 太小、无完整 snapshot 等候选无需申请 writer barrier。

Mac Demo 未重新编译或替换镜像、未修改 Gateway、未改变 Snapshot 周期配置、
未执行真实 WAL 自动封段或自动删除。复核曾有 `UNV4GJ` 短暂
DEGRADED（38/40），随后自行恢复；最终
`tests/check-demo-tenants-readonly.py` 得到 **10/10 RUNNING**、
每租户 40 活动委托、双边 10 档，现场证据：
`~/.opentradingcore/local-md-release-candidate-20261011/artifacts/tenants-after-common-wal-seal-ledger-recheck-20261012.json`。
Order A/B/C、Trade A/B、Robot 均无新增 OOM/重启。

## 真实物理封段尚未完成的工作

Common Ledger 和 Coordinator 是**事务调度/恢复拒绝机制**，
不会自动操作 Chronicle Queue 文件或提供真实权威证明。
还必须在 Order、Trade 分别实现适配器：

1. 独占 writer/recovery barrier、线程亲和 appender 和异步
   Reader/Tailer 版本代际管理；业务快路径不允许遍历旧 archive。
2. 文件 move/replace 和新基线持久化必须具有可恢复
   durable archive manifest，断电到一半只能停留 NOT_READY，
   不得恢复旧 writer 重复提交。
3. 跨多个 archived segments 的 Replica catch-up、
   Projection GAP、业务 committed-prefix 重放和冷启动验收。
4. SIGKILL 在**真实** Chronicle Queue 关闭/重命名/fsync
   每个窗口下的故障注入；对持仓、挂单、资金、Projection 水位对账。
5. 通过 TPS/P99/CPU/IO 基线与压力测试后，才以默认关闭参数
   灰度启用自动封段；自动删除仍须独立开门。

此前 Order/Trade 相关验证分支分别为
`codex/order-wal-archive-read-canary-20261012`
（`77b0d8e`），
`codex/trade-safe-wal-archive-canary-20261012`
（`be17fb8`）。
