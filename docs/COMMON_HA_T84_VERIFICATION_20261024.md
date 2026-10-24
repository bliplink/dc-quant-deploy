# Common T84 源码整合与真实双向故障验证（2026-10-24）

## 源码交付
- 基于远端 Common `saas-crypto` 510aaee 的独立分支 `feat/common-t82-certified-custody-20261024`，已推送整合提交 `f833749`；额外集成 T82 双收据持久账本、V19 WAL hotpath/source 和 RF2 仅 staged RECOVERING 的自动接管行为。
- 用本地 Java 8 / Maven 3.9.11 完整 `package`：97 个 surefire suites、439 tests、0 failure、0 error、0 skipped；JAR `com.app.common-3.0.22-SNAPSHOT.jar` SHA-256 `df7ecc99c6dd79e05dc37c04186c63db65c3f03c83508ab2bf7c1586da79e7a8`。
- 使用 T84 独立 Docker Compose（3 ZooKeeper + 两个真实 Netty JVM + 独立 WAL volumes）运行来自最新 Common 源码构建的 JAR。V19 Demo 驱动/状态机 harness 仍由旧隔离 `/tmp/v19` 类提供，故不代表正式 Order/Trade 无覆盖类生产集成。

## 真实故障时间线（UTC、2026-10-24）
- T84 已观察 A/B 在 Epoch 3 和 Epoch 5 恢复严格 READY；真实客户端 16 笔严格 ACK 全部成功，seq297→313，2 workers，3.36 ACK/s，p50=515.186ms，p95=1117.624ms。
- 10:18:49 SIGKILL Replica B，10:19:08 重新启动 B，A 自动经历 Epoch 6 `AUTO_DEGRADED_LOCAL_DURABLE`、Epoch 7 双物理 Custody 重新核验，10:19:46.780 恢复严格 READY；之后 16/16 严格 ACK seq313→329，2.64 ACK/s，p50=741.024ms，p95=1176.353ms。
- 10:20:37 SIGKILL Primary A；10:20:51.308 B 进入 Epoch 8 `RECOVERING`，10:20:56.489 B 降级 READY（明确 `quorumDurable=false`，并非 2/2）。10:21:24 启动旧 A 作为学习副本；B Epoch 9 经过 WAL、签名、双账本核验后 10:22:01.540 严格 READY。之后 B 的 16/16 严格 ACK seq329→345，1.86 ACK/s，p50=882.628ms，p95=1799.932ms。
- 最终双 JVM `P000.wal` SHA-256 完全一致：`b8937fb347bb25ba03059b2e5e0e23c944a164fd87e43d55fd110803b085ccf9`；Epoch 7 双账本 SHA 均为 `1e556027ac8bcf535bc849faf666c9334d0e90d6c0406948a33f626b00076d89`；Epoch 9 均为 `b481ee1379e41828318aca7a1a1be3e795cec96639a58a53f4972f976aeaa328`。
- 实测起始 8 次 `--local` 驱动请求取得 8 个物理 ACK/seq 增量，但返回模式是严格 `QUORUM_DURABLE`，不符 local 断言，故驱动 8/8 模式断言失败；不得记为 local ACK 成功，也非数据丢失。后续使用正确 `--strict` 完成成功证据。

## 安全与结论
- **隔离 Common + Demo A↔B 自动主切、签名双回执、WAL 一致性：局部 PASS**。人工仅执行 SIGKILL/恢复容器，epoch promotion/READY 由控制器自动完成。
- **性能 NO-GO**：严格 ACK p50=515–883ms (以上 3 段)，故障至单节点降级 READY 约 19.5s；恢复到严格 2/2 数十秒。和 `<5–10ms`、`<1s`、`1–2k msg/s/分区` 相距很远。只是少量请求的测试分布，不是生产 SLA。
- **完整集群 NO-GO**：仍缺 256 分区负载、10/50/200 租户稳定压测、真实 Order/Trade/MD/Projection 完整业务对账。T84 只用于 Common 快速验证；不得称为正式业务验收通过。
- **路线二立即开始“代码级集成准备”**：Order/Trade 共用正式 Common 状态机 API、非主节点构建/配置预检、真实业务测试用例准备可并行开展；但正式镜像切换和生产 Ready 必须等完整 HA 数据正确性门禁通过。
- 证据卷未删除；Mac mini 当时剩余磁盘约 23GiB（总盘使用 95%）；任何进一步负载测试前须先处理磁盘空间，不可清除 T84 证据卷。
