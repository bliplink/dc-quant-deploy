# MD-C 本地故障注入与恢复验收 — 2026-10-14

## 本地部署与真实操作

使用本地编译的 ARM64 MD 镜像 dc-saas/mdsvr:cluster-dev-local-mdqa-026306b-20261014，依赖 common 3.0.19。ZooKeeper 预检确认 MD-C 仅为 Learner、A/B 各持有 128 个 Primary 后，仅对 MD-C 执行一次 SIGKILL，随后用原本地镜像 Compose 单节点重建。没有重启 Order A/B/C 或 MD A/B，没有改 Gateway 或清空数据。

## 已核验

- SIGKILL：2026-10-14 08:18:50（Mac mini +08:00）。
- 容器重建：08:18:51；Spring Boot 服务启动完成：08:19:33。
- 第一条新的 MD_MARKET_READY：08:19:37；从 SIGKILL 到市场重新 READY 约 47 秒（包括 Java 初始化）。
- 11 个租户市场均重新打印一条新 MD_MARKET_READY，全部仍为 LEARNER。
- ZK 256/256 分区 READY，MD-A Primary 128 / MD-B Primary 128，MD-C 成员恢复。
- Gateway 对 3 个租户的公共 querySymbol 查询及匿名管理接口拒绝回归均通过；交易终端 HTTPS 200。Order 三副本此前 11/11 Snapshot 字节一致。
- 证据摘要：evidence/md-c-learner-sigkill-local-20261014.json；详细原始记录保存在 Mac mini ~/.opentradingcore/md-qa-20261014。

## 尚未完成：MD Primary 自动主切

本次只证实非 Primary 的 Learner 故障恢复，不代表主节点自动晋升完成。现网预检仍明确 BLOCKED，不能执行 MD-A/B SIGKILL。

排查确认只读预检的五项安全阻断目前是代码中固定的拒绝项，并不是五条实时运行健康失败。生产源码的 MdAutomaticFailoverService 默认 md.cluster.failover.enabled=false，而且没有可注入的生产 MdImageRecoveryFailoverController.Safety 实现。安全校验需要旧发布者 fencing、权威 Order 全量 Image/Delta、RECOVERING→READY 发布 Epoch 隔离和故障后 Robot 对账。不可通过放宽预检或空的 Safety 回调绕过。

另外，当前 Order-B 承担 256 个 Order Primary；写入排空、权威持久 Replica 水位、Projection 对账都尚未认证前不能重启它。本次不增加公共机制，不改变既有数据、Snapshot/WAL 和 Gateway。

下一步只针对现有运行时缺失的 Safety 接线与验收证据处理；完成后再执行受控 MD Primary 故障注入。
