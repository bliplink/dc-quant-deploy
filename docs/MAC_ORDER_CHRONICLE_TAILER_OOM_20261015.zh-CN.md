# Mac Demo｜Order Chronicle WAL 同步 Tailer 泄漏与修复验收（2026-10-15）

> **来源：真实运行中的 10 租户 Demo，非合成测试。此记录是 Demo 修复和持续观察证据，不能授权 HA 故障切换。**

## 故障链

初始 10 租户 / 400 笔 Robot 挂单（20 bid + 20 ask / 租户，每秒刷新且 Tape 每秒触发）在长时间运行后，Order A/B 复制状态批处理逐步变慢，观测 `stateReplicaMs` 和 `commitReplicaMs` 由秒级增加至 15–36 秒，Gateway `cancelBatchOrder` 多次 60 秒超时，Robot 依次变成 `DEGRADED` / `ERROR`。Order-C 在 **2026-10-15 14:52 CST** 因 Java 进程内 `OutOfMemoryError: GC overhead limit exceeded` 退出并自动重启。Docker `OOMKilled=false` 不能否定 Java 堆 OOM。

故障时三节点配置相同：`-Xmx2048m -Xmn512m -XX:MaxDirectMemorySize=256m`，每个 Docker 容器 3 GiB / 1.5 CPU；Order-C 担负 256 个 sync Replica 分区。Order A/B 在 JVM heap `jstat` 中 ParOldGen **93.57% / 91.46%**，累计 Full GC **74 / 53 次**。对象直方图（Robot 已暂停，`jcmd GC.class_histogram -all`）发现：

| 类型 | Order A | Order B | 刚自动重启的 C |
|---|---:|---:|---:|
| `ChunkedMappedBytes` | 925,786 | 987,805 | 几千 |
| `BinaryWire` | 925,530 | 987,549 | 几千 |
| `StoreTailer` | 308,433 | 329,133 | 几千 |

**主要问题已定位到 `OrderPartitionJournal.syncJournalThrough()`：** 对每个需证明持久化的 WAL 末尾 `createTailer()`，只在 `try (DocumentContext ...)` 中关闭 DocumentContext，却从不关闭 Tailer 自身。每次严格副本 ACK 逐步遗留 Tailer 和 Chronicle 映射/Wire 对象；同步复制吞吐和 GC 被放大影响。

## 已完成修复与直接部署

- [Order PR #12](https://github.com/bliplink/com.app.dc.ordersvr/pull/12)，源码 SHA `653ee41`，建立在待整合的统一 Order PR #11 上。将严格尾帧位置校验和 `MappedBytesStore.syncUpTo(..., SYNC)` 保留在 `try (ExcerptTailer tailer = state.queue.createTailer())` 中，退出时关闭 Tailer。**不修改提交水位、原始 WAL、ACK 语义或 Gateway。**
- 增加 96 次 `append + 2 次 sync` 及重新打开后最后序号仍为 96 的回归；Mac Java 8 的 `OrderPartitionJournalTest` **14/14 PASS**。全量 Order 回归请求被执行环境安全检查阻止，因此**没有**宣称全量通过；PR 继续为 Draft 候选。
- 本机离线 ARM64 修复镜像 `dc-saas/ordersvr:chronicle-tailer-close-v3-local-20261015`，基于此前统一 Common 候选 `dc-saas/ordersvr:certified-v2-local-20261015` 单类覆盖。Common Jar SHA-256 保持 `af14b091151feba2caf384ae8652065fa1b12de8ef27af57b57fe955187d71de`。带 `dc.release.authorized=false`，非正式生产授权 GHCR 版本。
- 依用户此前授权直接更新 Demo 而非逐节点灰度：先停止 Robot 新流量，确认 Order 256/256 ZK assignment / 三节点 Snapshot 一致、Projection DB tail Order/Trade 各 10 项匹配，保存旧 env/镜像回滚数据；同时停止 Order A/B/C，使用新镜像重建三容器，**不删除任何 WAL、Snapshot、MySQL、租户状态**。
- 重启后 Order 256/256 READY、Snapshot 一致、Projection 10/10 DB 尾部匹配，三容器 RestartCount 0 / OOM false。冷启动 RAM：A 约353MiB，B 382MiB，C 369MiB。数分钟后运行 Robot 负载时 Chronicle `ChunkedMappedBytes` 数 A=3343、B=3361、C=2974，`StoreTailer` A=967、B=999、C=906；旧版对象数百万数量级的问题**暂时没有重现**。但**数分钟样本不能代替 24h 稳定性测试**。
- 为区分内存泄漏和高频撤单量，在本机数据库对 **全部 10 个已启用 Robot** 做了可回滚的临时节流：报价刷新 `1000ms→10000ms→30000ms`，Tape `1000ms→3000ms→5000ms`；**20 bid + 20 ask、Robot/Tape enabled 仍保持不变**。原始间隔备份位于本机 `acceptance-evidence/robot-rate-throttle-backup-20261015.tsv`，未上传 Git。
- 新 Order 修复镜像下，8 个可交易租户已恢复 `RUNNING`，合计 320 笔挂单；另两个 Trade P190/P220 仍被已知原始 WAL 冲突的持久标记隔离，保持 ERROR，不许强制 READY。某次 Gateway `cancelBatchOrder` 8/8 成功、均值 83ms。**这不是 10/10 Demo 或 HA 通过。**

## 尚未通过

1. 更长时间（至少持续 10 租户原负载/配置合适时）观察 Order Heap/Full GC、Java Tailer/ByteStore 计数、同步副本 p95/p99 ms，确认泄漏不会在同一热路径之外再出现；另有 replay/readBatch 等冷路径 Tailer 创建点需要审查是否也应显式关闭。
2. 8 核约 15.6 GiB Mac VM 不是 200 租户容量证明。临时数据库节流未修改自动注册租户的默认模板，因此以后 fresh install 应把 Demo 速率参数配置化，并分别测 10→50→200 的吞吐与滞后。不要为了性能取消 WAL msync / 同步副本 ACK。
3. P190/P220 的完整原始 WAL 已提交区间在双方只读编码层面匹配（见 `MAC_TRADE_COMMITTED_PREFIX_READONLY_AUDIT_20261015.zh-CN.md`），但新 Trade 接收端的独立物理 Quorum、恢复事务和外部权威对账尚未闭环。**未执行 SIGKILL，未开放 Trade READY，未删除 WAL。**

## 本机回溯路径

- 本机证据：`~/.opentradingcore/otc-demo-direct-20261015/acceptance-evidence/order{svr,svr-b,c}-heap-classes-20261015.txt`（部分名称可能不同，以实际目录为准）、`order-chronicle-v3-rollback.json` 和新镜像构建日志。
- 原 Compose env 与新 Compose env：同目录下的 `demo-ordered-trade-v5-20261015.env`、`demo-ordered-order-chronicle-v3-20261015.env`，**包含真实访问凭据，不可入库**。完整旧业务数据 `~/.opentradingcore/dc-saas-runtime-ordered-20261015` 未被清理。
