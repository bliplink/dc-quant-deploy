# Mac mini Demo：Order/Trade 定时快照启用与 WAL 归档边界（2026-10-12）

## 结论

本次在 **当前 Mac Demo 运行实例** 启用了 Order A/B/C、Trade A/B 共五个服务的周期快照调度。
所有配置项通过运行目录中的 `control/overrides/*/config/application.properties` 挂载，
已经依次重启各服务使 Spring `@Value` 生效；此外更新了私有
`~/.opentradingcore/local-ha-zkfix-20261011-v1/artifacts/local-ha-runtime.env`
中配置生成器使用的同名变量，避免下一次生成配置时恢复为 `false`。
该私有文件可能含凭据，**不得提交 Git**。

| 配置项 | Order A/B/C | Trade A/B |
| --- | --- | --- |
| `*.snapshot.periodic.enabled` | `true` | `true` |
| `*.snapshot.periodic.pollMillis` | `60000` | `60000` |
| `*.snapshot.periodic.maxAgeMillis` | `3600000` | `3600000` |
| `*.snapshot.periodic.minCommittedMutations` | `20000` | `20000` |
| `order.cluster.snapshot.periodic.maxPartitionsPerRun` | `1` | 无该参数；单轮最多选 1 分区 |

这表示**调度器已启动**，不表示每分钟都一定有快照：只有候选分区存在新的
committed state / mutation，且达到阈值或上次快照足够旧时才真正执行。
Order 快照还会复制到副本；默认 5s 轮询 + 一轮 4 个分区的参数**未启用**。

## 现场证据与故障

- 五个容器在 2026-10-12 10:03–10:11（Asia/Shanghai）逐个滚动重启。
  五个日志均发现 `Order periodic snapshots started` /
  `Trade periodic snapshot started` 对应启动日志。
- Order 主备分区只读核验 **256/256 READY**。滚动重启时，P104 快照 A 较
  B/C 短暂落后，随后三节点 snapshotId/序号归一，重新严格运行
  `tests/verify-order-cluster-state-host.sh` **PASS**。应用快照同步非原子跨节点观察，
  单次读到过渡期不代表恢复证明无条件通过。
- Trade 恢复较慢：Trade-B 的 P023 / epoch 7 在 10:19:15–10:19:16
  依次记录 `TRADE_RECOVERY_CHECKPOINT_SAVED`、
  `TRADE_PARTITION_UNCOMMITTED_TAIL_ARCHIVED` 和
  `TRADE_PARTITION_READY`。说明**按恢复/rebase 触发的真实 WAL 归档运行了**，
  但**不能证明存在定时业务 WAL 轮转控制器**。
- 重启期间多次对 `queryTradePosition` 的请求因
  `PARTITION_NOT_READY` 被拒，Robot 中有租户临时转 ERROR。
  P023 恢复后最后的 `FT9B21` 自动恢复；
  10:19 的 `tests/check-demo-tenants-readonly.py`
  返回 **PASS_10_TENANT_SNAPSHOT**：10/10 RUNNING、各 40 活动委托、
  双边各 10 档。证据位于私有 artifacts 的
  `tenants-after-p023-ready-20261012-1019.json`。
- **10:21:00 实际快照落盘证据**：Trade-B `P054/latest.json` 更新为
  epoch=2、snapshotSeq=201206、committedStateSeq=201205，现场日志对应
  `TRADE_SNAPSHOT_SAVED partition:P054, locations:1, epoch:2`。
  在调度已启用、未手工调用捕获的条件下，说明 Trade 的低频定时任务已
  产生一次真实业务快照；这不是 P023 的 `TRADE_RECOVERY_CHECKPOINT_SAVED`。
  Order 的周期性 `ORDER_PERIODIC_SNAPSHOT_OK` 仍待在满足提交变更阈值后观察，
  不应将之前随重启/复制更新的快照文件混作 Order 定时任务成功证据。
- **最终复核**：重新以退出码严格检查 Order 全 256 分区 PASS，
  `snapshot_sets_equal=256`、无 Learner；随后再次运行 10 租户只读审计 PASS，
  10/10 Robot RUNNING、每户 40 笔活动委托、双边各 10 档。
  最终证据：`artifacts/tenants-periodic-final-20261012-1023.json`（Mac 私有目录）。
- 现场曾触发多租户恢复期间的短暂失败，因此本轮不宣称长时间稳定性、
  Trade 主切全覆盖或稳定 TPS/P99 验收通过。
- 由于 Trade-B 和 Robot 原始容器内存接近上限，本轮将
  `TRADESVR_B_MEMORY_LIMIT` 先由 896m 升为 1536m，后在业务恢复后
  观察到 1.406 GiB / 1.5 GiB，故继续增加至 **2048m**；
  `ROBOTSVR_MEMORY_LIMIT` 由 384m 升为 640m。
  `docker update` 与私有运行环境配置同时更新，**JVM Xmx 未扩大，也未再次重启**。
  后续必须观察内存峰值和 CPU，不能据此推断内存问题完全修复。

## 归档 / GC 的三种不同含义

1. **现役 Chronicle Queue WAL**：继续写入；不可删除。
2. **rebase/恢复产生的 sealed 历史 .archive**：
   Order 与 Trade 现有逻辑已经支持，Trade-B 本次真实发生过未提交尾部归档。
3. **正常 epoch 内的定期 WAL 安全封段/压缩/备份/自动删除**：
   这不是周期快照本身的工作。当前代码没有独立可信的正常期
   自动归档/GC 轮转控制器；
   **不能将 `snapshot.periodic.enabled=true` 宣称为业务 WAL 自动轮转已上线**。
   必须将完整提交证明、各 Replica durable watermark、Projection durable watermark、
   已关闭文件引用和可恢复备份链接到 retention fence，随后才能另行启用。

本次未在 Gateway 增加任何逻辑、未清空租户/数据库、未关闭同步复制、
未允许基于文件日期删除业务 `.cq4`。

## 运维复核及回滚

- 运行配置实际路径：
  `~/.opentradingcore/dc-saas-runtime-zkfix-20261011/control/overrides/{OrderSvrA,B,C,TradeSvrA,B}/config/application.properties`
- 每个原配置有相同目录下的 `application.properties.before-periodic-20261012-1000`
  备份；私有环境文件也单独备份且权限 0600。
- 发现持续的 `PARTITION_NOT_READY`、快照复制失败、P99/TPS 明显下降、
  OOM、Robot 永久 ERROR 时应**停止继续灰度**、留存现场证据，然后
  在确认恢复窗口安全后，分节点恢复 `*.snapshot.periodic.enabled=false`
  并滚动重启；不要在未证实业务副本健康时同时重启主备。
- 数据面的 `ORDER_PERIODIC_SNAPSHOT_OK` / Trade 新 snapshot 时间戳、周期
  持久水位与跨节点 checkpoint 对账，是下一轮完整功能验收的必要证据。
  单有 `started` 日志不代表磁盘快照成功生成。
