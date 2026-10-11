# OpenTradingCore Demo 按日期保留自动回收开关（2026-10-11）

## 设计目标及边界

- **Demo：** 使用 `enabled` 和各类 `RetentionDays` 按日期保留日志，**不设置磁盘使用率或剩余空间触发阈值**。独立 macOS 用户级 `LaunchAgent` 每 **24 小时**启动一次 Python，扫描结束即退出；无持续线程、无 ZooKeeper/数据库请求，不占用 Order/Trade 撮合线程。
- **生产：** 默认 `enabled=false`，不自动删除。后续由磁盘监控触发独立、带副本/Projection/恢复证明的存储运维操作。不能把 demo 规则直接打开用于生产。
- **重要限制：** 该工具**不清理活动 Chronicle Queue `.cq4` 或任何包含业务记录的归档 WAL**，所以仍不能保证磁盘永远不会耗尽。Order/Trade 周期快照不会自动截断旧活动 WAL；长期 Robot 压测的 WAL 增长问题还需完善“快照 → 副本/Projection durable watermark → 闭合分段 → 可验证安全删除”。清理被文件句柄阻断时记录 `blockedReasons`/`warnings`，不冒险删账本。

## 配置

仓库提供 `config/retention-demo.json`（Demo 初始 `enabled=true`）和 `config/retention-production.json`（`enabled=false`）。

Demo 重要配置：

- `enabled`：总开关，`false` 时不扫描、不删除。
- `environment`：`demo` 或 `production`；本实现**拒绝生产开启自动删除**。
- **不再使用磁盘阈值**：只依据文件修改日期是否超过保留天数判定候选。磁盘占用与剩余空间仍写入状态 JSON，供后续监控显示，但不参与删除决策。
- `rotatedLogRetentionDays: 2`：仅 `runtime/log` 下的日期后缀轮转文本日志。
- `emptyBootstrapRetentionDays: 2`：只清理 `OrderSvr[A/B/C]/journal/.archive` 下，**epoch0-seq0 且仅含精确 128KiB metadata.cq4t** 的旧空队列，且 `lsof` 确认文件未打开。无法检测句柄、目录变化、符号链接或真正业务 `.cq4` 一律保留。
- `maxDeletedBytesPerRun: 1073741824`、`maxDeletedFilesPerRun: 100`、`maxCandidatesPerRun: 150`：每天执行一次的容量/候选数量保护，防止清理任务占用过多 IO。保存 `nextCandidateCursor` 并在下次运行轮转扫描顺序，避免 Colima 一直打开的前 150 个元数据目录导致后续分区永远得不到检查。
- `dryRun: true`：只记录候选，不删除；用于保守演练。

**注意：** 不扫描 `runtime/data` 下的 MySQL、ClickHouse、MD OHLC、Trade/Order 活动 WAL，也不调用 Docker image/volume prune。不会按日志日期强行删除正在打开的文件。

## Mac mini 安装与管理

在 `dc-quant-deploy` 根目录：

```bash
python3 scripts/manage-demo-reclaim-launchd.py \
  --runtime-root "$HOME/.opentradingcore/dc-saas-runtime-clean-20261010" \
  --interval-seconds 86400
```

安装器同时把旧版本 `highWatermarkPercent`、`criticalWatermarkPercent`、`minFreeGiB` 配置迁移掉（保留原保留天数和 `enabled`，自动备份旧配置）。安装器将脚本复制至 `$HOME/.opentradingcore/maintenance/bin/auto-reclaim-demo.py`，配置持久保存为 `$HOME/.opentradingcore/maintenance/retention-demo.json`，首次安装会创建 `~/Library/LaunchAgents/com.bliplink.opentradingcore-demo-retention.plist` 并注册启动。配置由运行器每次读取：**修改 `enabled` 无须 Docker 或应用重启**。卸载 Agent（不删除配置和审计报告）：

```bash
python3 scripts/manage-demo-reclaim-launchd.py --uninstall
```

状态文件：`~/.opentradingcore/maintenance/retention-status.json`；日志：`retention.stdout.log` 和 `retention.stderr.log`。状态里包含使用率、剩余 GiB、回收候选、真实删除次数及字节数、阻断原因、`decision`、`warnings`；监控可直接读取这份 JSON。文件因打开句柄等安全理由不能清理时将记录 `EXPIRED_FILES_BLOCKED_BY_SAFETY_GUARDS`；无过期候选则正常结束。每次运行都会检查已过期的候选，**不因磁盘占用率较低而跳过**。

## 两天归档与快照恢复之间的关系

- **核心恢复公式：** 已经持久化并经权威校验的完整快照 `S`，加上从 `S.snapshotSeq+1` 开始没有缺口的已提交日志，才能恢复 `S` 之后的状态。快照必须足够完整，并被所有需要追平的副本可靠安装。
- **安全删除上限不能只按日期计算：** 对某个分区，清理前要同时取得最新有效快照覆盖水位、每个仍需恢复的副本 durable/replay 水位、Projection 持久消费水位，以及故障回滚需要的最早记录。仅当归档结束序号不超过所有相关水位共同允许的删除上限、归档已关闭且超过 2 天，才允许回收。
- **快照频率高会降低保留旧日志的需求，但不替代水位证明。** 如果某副本失联超过 2 天、快照传输失败、Projection 滞后，或回滚标记仍在旧归档中，系统应暂缓删该分区的归档并报警，而不是强制执行时间删除。
- **目前该轻量 Demo Agent 尚不删除业务 `.cq4`：** Order/Trade 现网 `snapshot.periodic.enabled=false`，即使调整为较高频率，现有代码也只是做快照，并不会自动产生完整的安全 WAL GC 水位判定。因此现在两天保留期实际适用于普通轮转文本日志与已关闭空初始化归档，不能把它宣称为 Order/Trade WAL 已具备两天自动裁剪。

## 验证结果

- 按天回收专项 **13/13 PASS**（包括候选轮转公平性），既有归档审计 **14/14 PASS**。
- 隔离测试覆盖开关关闭、即使磁盘空间充足也按日期清理过期日志、活跃 WAL 绝不删除、空初始化元数据已打开时保留、模拟关闭后可回收、数据归档拒绝、磁盘水位仅作信息展示、候选/删除额度及符号链接隔离、生产开启失败。
- Mac mini 2026-10-11 实际 date-only smoke：当前磁盘占用约 64.7%，空闲约 162.5GiB；无需等待使用率达到阈值，运行结果 `decision=RETENTION_APPLIED`、实际 **0 删除**（当前没有满足 2 天保留条件且允许安全删除的候选）。
- **这不是“业务 WAL 仅保留两天”的实现**：两天仅适用于已轮转普通应用日志和未被使用的空初始化归档。若要 Order/Trade 业务 WAL 也只保留两天，必须把已经成功持久化的完整快照作为恢复基线，同时对所有副本、Projection、回滚/补历史水位完成证明；仅提高快照频率或等待两天仍不够。当前 Order/Trade 周期快照在现网均为关闭状态，因此不能假设已经建立可裁剪基线。
