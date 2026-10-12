# Trade Projection Archive GAP 实证修复、镜像候选与 Replica 维护事故（2026-10-12）

## 本轮真实完成（不等于线上修复）

源仓库 `bliplink/com.app.dc.tradesvr` 验证分支
`codex/trade-safe-wal-archive-canary-20261012`：

- `e61c02ca348834883182518abefcbf070bc2ffe7`：
  修复 `TradeProjectionCommittedReader` 的两处历史 GAP 错误：
  1. 以前只要 MySQL watermark 早于当前 Snapshot baseline，
     就直接拒绝并返回 `BASELINE_MOVED`，即便 WAL 归档尚完整；
  2. 较大跨度的 GAP 使用 `TradePartitionJournal.readBatch`，
     但它只读当前 Chronicle generation，不能读 archived WAL。
  现在对合法的非零旧水位改为**实际按顺序读取保留归档**；
  历史缺失、序列跳跃仍按 `BASELINE_MOVED` fail-close；
  初始未知/零水位仍不得跨 rebase 盲目重建。
  新 `TradeProjectionArchivedGapRecoveryTest` 覆盖两段归档、
  物理缺失以及 dirty/uncommitted tail 不泄露。
- `2ed60956ab137ddf25044add9e82256d4eb0e7b5`：
  针对每个 archive page 都从段头遍历的 O(N²) 补读模式，
  利用 Chronicle firstIndex + 段持久化 baseline 计算候选 index；
  **必须在业务记录 seq 精确相同后才采用**。
  索引跨日期 roll-cycle 不合法、缺失或不匹配时
  保留原先的慢速顺序扫描；
  **不改变在线 append、Replica 复制、READY 或 Gateway**。
  新组合全量 Java8 Maven `286/286` 通过，0 fail/error/skip。

本地构建的新镜像
`dc-saas/tradesvr:cluster-dev-local-c6b8fe7d-20261012-archive-gap-fast-2ed6095`
源码 HEAD 2ed6095，Common JAR SHA256 为
`34a6ee05db748eb2990f68b1dc86188a41ca52c320e1838b9cd82fd3c77a0363`。
通过 Docker 无网络隔离镜像文件系统检查和 Java 全量回归；
**仍未上线任何 Primary Trade-B 镜像**。
Common 仍用未正式发布的本地开发坐标
`3.0.17-dev6b8fe7d20261012-SNAPSHOT`，
Trade 的隔离构建使用另一个 dev `com.app.dc` Maven 坐标，
正式 GitHub Actions 依赖版本链**尚未发布**。

## 六处真实 MySQL watermarks 的物理 Archive 离线 E2E

Mac 支持 APFS `cp -c` copy-on-write。把 B 的六个
实际历史分区 `P023 P054 P060 P077 P244 P246`
共 13 个源归档目录（各分区的原始 `.cq4` 和
`baseline.properties`）以及**当前基线的只读复制**
克隆到了专门隔离区：
`~/.opentradingcore/local-ha-wal-seal-20261012-v1/artifacts/trade-real-archive-gap-fixture-e61c02c/`。
私有复制路径作为 Java8 单测 `/fixture` 卷启动；
临时在线取证单测未提交到正式源码集，也未打开生产业务
WAL 写入句柄。

真实 `TradeProjectionCommittedReader.read` 在每个
MySQL 原始水位上，从最新归档 + baseline 重建后返回 `OK`，
首批为下面两个已经在源端提交的 `STATE_BATCH` 事件：

| 分区 | MySQL 旧水位 | Clone 最新业务基线 | 输出首两条 seq |
|---|---:|---:|---|
| P023 | 219475 | 286689 | 219477, 219479 |
| P054 | 223429 | 295301 | 223431, 223433 |
| P060 | 215797 | 285011 | 215799, 215801 |
| P077 | 213139 | 282043 | 213141, 213143 |
| P244 | 214965 | 286689 | 214967, 214969 |
| P246 | 212879 | 283559 | 212881, 212883 |

六个分区的已提交业务事件可从物理 Archive 补读。
注意测试仅请求每个分区的前两条事件，**不代表
数万条完整补录或 MySQL 投影已经完成**。
采用索引定位后的两分区隔离试验执行时间从约 4.8 秒
降至约 2.3 秒，仅为单次观察值，不是吞吐性能验收。

## 受控 Trade-A 镜像 canary：启动脚本错误自动回滚，但暴露架构风险

- 经 `docker inspect` 和文件 SHA 对齐，预创建
  `dc-saas-tradesvr-candidate-2ed6095`（未运行），
  与旧 Trade-A 保持一致的 host network、
  service env、5 个 bind mount、entrypoint/workdir；
  将**准备的候选容器**限制改为 2 CPU / 3GiB，
  原 Trade-A 仅 0.5 CPU / 1.5GiB。
- 从 Primary B 最新 Snapshot 复制、哈希验证、fsync
  十个分区合计 193079866 bytes，
  同时保留旧 A 的 10 份回滚副本：
  `artifacts/trade-a-v12-sealed-snapshots-20261012`。
  以 live read-only Chronicle Queue 验证 10/10 B
  Snapshot 的物理 `STATE_COMMIT` 存在于 A WAL，
  epoch、业务提交 state 水位均匹配；
  实时 ZK 10/10 B Primary/A Replica/READY，租户审计
  10/10 PASS。
- 北京时间 18:52 左右受控停止 A、安装十份 Snapshot，
  将旧 A rename 为 backup、候选 rename 成
  `dc-saas-tradesvr` 并执行 `docker start`；
  **发布脚本错误地使用** `state['State']['RestartCount']`
  而非 `state['RestartCount']`，发生 `KeyError`，
  因此自动回滚：停止新 A，将其保留为
  `dc-saas-tradesvr-failed-2ed6095`，旧 A 恢复原容器名、
  所有旧 Snapshot SHA 回滚、旧 A 重新启动。
  B 镜像从未替换，新候选容器启动时间不足以证明
  Spring/ZK 业务健康；**新版本不能标记线上验收通过**。
  发布脚本本地已修正该字段错误，且加入未明确确认
  同步复制维护期则 fail-closed 的保护，不再自动运行。
- 更重要的是，在线 B 配置
  `trade.cluster.replication.required=true`，目前只有
  **单一物理 Replica A**。A 停止即令 Primary B 向
  `127.0.0.1:19221` 的复制 TCP `Connection refused`；
  同步复制 fail-close 导致 Trade 写入中断并出现
  uncommitted `STATE_BATCH`，随后不得不开启
  `TRADE_PARTITION_UNCOMMITTED_TAIL_ARCHIVED` 分区恢复。
  在当前二节点同步复制协议下**无法通过简单停 A 实现
  零停机滚动升级**。这是架构事实，不可只靠改脚本修复。
- 回滚后曾出现 10/10 Robot DEGRADED/ERROR，
  不可称为成功。B 的分区恢复自动推进中，
  18:54:10 约 2/10，18:55:09 约 3/10，
  后续以`tenant-recover-after-a-v12-rollback-poll-*.json`
  实测为准。

## 严格剩余门禁

1. **先恢复所有 10 租户**（机器人 RUNNING +40 open
   orders+两侧盘口10档），不再主动故障注入。
2. 稳定后检查 Order/Trade/MD/Projection、MySQL
   水位连续性、资金、仓位、订单，确认 dirty tail
   rebase 之后 A/B 的权威 committed prefix。
3. 在保证两个已确认副本仍可满足持续复制的前提下，
   实现第三节点/受控成员替换与同步复制切换；
   或在明确接受交易暂时不可用的 Demo 维护期
   做有门禁的停机升级。不可把强行取消
   `replication.required` 当作 HA 方案。
4. 待成功滚动发布含 2ed6095 的 B，再验证
   MySQL 这六处分区水位真实跨 Archive 前进，
   且没有重复成交 / projection event、资金持仓一致。
5. 最后才开启 WAL 自动删除和 200 租户压力测试。
   Gateway 透传逻辑未改动，真实 WAL GC 继续关闭。

所有运行日志和离线归档都仍在 Mac 的
`~/.opentradingcore/local-ha-wal-seal-20261012-v1/artifacts`
或业务原路径下；未删除在线 WAL。
