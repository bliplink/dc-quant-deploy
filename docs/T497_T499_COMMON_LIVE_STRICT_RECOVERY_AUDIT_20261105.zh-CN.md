# T497–T499｜Common 统一恢复边界与真实 A/B/E4 严格提交验收（2026-11-05）

## 结论

**Demo + Common 的真实 A/B 两次 SIGKILL、双向数据追平、E3 旧节点在线退休、E4 双 RSA 恢复、三节点 ZK 严格 READY 以及 E4 新业务 2/2 `QUORUM_DURABLE` ACK 已分别实测通过。生产 Order/Trade 自动 HA 仍 NO-GO。**

这里的 Demo 故障续写是 **显式 C 独立 RSA 授权的 `LOCAL_DURABLE_ASYNC`**，保留客观 RPO 风险，不能追认严格 ACK。E3→E4 的新严格提交在两节点物理恢复并由 A/B 双 RSA 验证后另行启用。旧 LOCAL 期间的历史客户 ACK 不会被 retroactively 改成 QUORUM。

## 实测链路与输出

| 验收 | 实测证据与结果 | 性质 |
|---|---|---|
| T497 A/B 初始 | 原 A/B 独立 RSA Genesis、E1 两物理持久 ACK，状态 `40` | 真实三 ZK / 两 Docker JVM |
| T497 SIGKILL A | B 自动签署 E2 `RECOVERING`；Common 原始 A/B WAL/Custody + Snapshot 回放 `40` | 真实 SIGKILL，未伪造 READY |
| T497 E2 继续写入 | 独立长寿命 C 签署许可，B 状态 `60`，`quorum=false`, `rpoRisk=true` | 实际 LOCAL 业务持续 |
| T497 A 返回 | A 作为实际 ZK Replica 追平 E1/E2，状态 `60` | 物理 RSA 前缀及 fsync |
| T497 SIGKILL B | A 自动恢复 E3，签名回放至 `60`，C 再次签名许可，状态 `74` | 真实第二次 SIGKILL，LOCAL |
| T497 B 返回 + TCP | B 真正恢复 E3 作为 Replica，A 新写入通过纯 TCP 签名复制，双方状态 `85`，请求 `7` | B 原始 WAL fsync 及业务重放 |
| T498 E4 基线 | A、B 独立物理 JVM 签名封存业务 `85 / 7` 的 E4 Snapshot | 独立双 RSA Snapshot |
| T498 活 E3 → E4 | 在线 E3 A 主/B 备关闭物理 WAL/Netty，独立签署 E3 retire；A/B 各执行 E4 Snapshot 业务回放并签署恢复回执；同一真实三 ZK E4 STRICT `READY` CAS | **真实在线双节点退休**，旧验证缺口已补 |
| T499 E4 新写入 | 在上一步新 E4 `READY` 上实际启动 A/B Netty；两条新 `byte[]` 客户命令返回 **`QUORUM_DURABLE`**，B 物理 WAL fsync 到 seq `2` | 新 Epoch 的真实 2/2 物理提交 |
| T499 SIGKILL E4 B | 再杀 B，A 的下一条写入返回复制异常，**没有客户 ACK**，不能追认 A 未确认尾部 | 无假 quorum 的拒写安全验收 |
| T500 真实严格故障 WAL 审计 | 对本轮 T499 真实物理卷 **只读重开**：A 实际 3 条、B 2 条，双 RSA/Custody 只认证 2 条；原始未确认第 3 条绝不重放，破坏副本原始 WAL/Custody 的测试均拒绝 | `CommonCertifiedStrictCrashPrefixTest` **1/1 PASS** |

全部这些命令真实退出 0，而非只对比文件名或依赖异步外部编译。使用 T497 Common 候选 JAR SHA-256：`2e12e10aa406b82e91efb4161a5c3a9e234b5c4c8039ada149540391c6f52b8a`。E4 A/B 基线 `a6e76d0b3f001f972fd7d63fee8360151e8db66c400edfbe08904a706833c8f4`。

**保留本机证据：**

- T497 真实双向 SIGKILL 完整日志：`.work/t497-common-ready-boundary/t497-real-ababa-full.log`；物理卷：`~/.opentradingcore/t124-live-kill-runs/20261105144402`。
- T498 真实活 E3→E4 记录：`.work/t497-common-ready-boundary/t498-live-e3-to-e4-execution.log`；隔离业务卷：`.work/t497-common-ready-boundary/t498-live-e3-e4-20261105145233`；独立 ZK `/dc/cluster/t280-20261105145233`。
- T499 E4 新严格交易 + SIGKILL B：`.work/t497-common-ready-boundary/t499-real-strict-ack.log`；新 Epoch WAL：`t498-live-e3-e4-20261105145233/new-strict-business/{a,b}`。
- Common JUnit 7 组 **60/60 PASS**：`.work/t497-common-ready-boundary/t499-common-regression.log`，含 T497 生产发布前业务安装强制门禁、T492 Snapshot pin、T491 定时签名 Snapshot、256 分区自动计划和 E4 STRICT rearm。

可复现入口（所有根目录用环境变量传入，不上传 RSA 私钥）：

- Common 仓库 `examples/common-only-demo/scripts/verify-real-live-e3-e4-strict-t498.sh`。
- Common 仓库 `examples/common-only-demo/scripts/verify-real-live-e4-strict-ack-t499.sh`。

T500 使用 T499 **同一组**新的 E4 磁盘，而不是之前 T287 的旧样例：`-Dotc.t287.real.fault=.work/t497-common-ready-boundary/t498-live-e3-e4-20261105145233/new-strict-business`，输出 `T288_REAL_E4_AFTER_B_SIGKILL_CERTIFIED_PREFIX_ONLY_PASS oldPrimaryFrames=3 dualCustodyCertified=2 exposedCommands=2 unackedTailExcluded=true`；包含损坏 WAL、缺失物理 Custody 回执、B 端不同未确认尾部拒绝验收，**不写回原盘**。

### T500｜同一 T497 Common JAR：256 分区真实双 JVM 严格提交压力复测

使用 `tests/run-t466-demo-common-256-strict-load.sh`，将 `OTC_T466_COMMON_JAR` 精确绑定上述 SHA-256 的 T497 候选 JAR，真实三节点 ZooKeeper、两个独立 Docker JVM、256 分区（A/B 各 128 Home）、严格 RSA/WAL/CommitIndex/双 Custody 客户 ACK：

| 模拟租户档位 | A 已 ACK / 失败 / TPS / p99 | B 已 ACK / 失败 / TPS / p99 |
|---|---|---|
| 10 | 20 / 0 / 8.06 / 469.535 ms | 20 / 0 / 7.54 / 535.902 ms |
| 50 | 50 / 0 / 19.37 / 281.638 ms | 50 / 0 / 20.57 / 232.940 ms |
| 200 | 200 / 0 / 30.80 / 465.579 ms | 200 / 0 / 28.85 / 442.818 ms |

双方逐分区原始持久 WAL **256/256 SHA 相同，540/540 帧字节一致**，验收输出 `T466_256_REAL_A_B_256_PARTITIONS_BITEXACT_PASS frames=540 partitions=256`、`T466_256_STRICT_TWO_JVM_STRESS_PASS`，命令退出 **0**。本机证据 `.work/t497-common-ready-boundary/t500-256-strict-load.log` 及 `.work/t466-common-256-strict/20261105071552-75565/metrics.json`。

**边界：** 10/50/200 是模拟租户请求并非注册的真实 SaaS 租户；仅证明 256 分区稳定严格提交/一致性，不包含注入这 256 分区的真实自动双向 SIGKILL，也未验证 Order/Trade 资金/持仓/投影与 Robot E2E。Mac 的现有 CPU/Docker 负载会影响 TPS/p99，不得宣称生产性能。

## 代码边界调整

1. T496 已从 `OrderCommonRecoveryBinding` / `TradeCommonRecoveryBinding` 删除业务侧原有的物理恢复入口（包括签名分段安装、旧主失败恢复、E3 反向恢复），两个业务绑定类现只暴露 `businessRegistry(request)`，即已有 `ReplicatedStateMachine` 工厂。两项反射及 Common 非认证恢复拒绝测试各 1/1 PASS。
2. T497 的 `CommonCertifiedNodeRuntime` 强制在 `signedPublisher.recoverAndPublish(stage)` 前先调用 `RecoveredPhysicalPartition.requireCertifiedBusinessInstalledBeforeReady(stage)` 和分区 `businessReplay` 校验；未实现的生产 Snapshot/WAL 安装器默认抛出 `COMMON_PRE_READY_CERTIFIED_BUSINESS_INSTALLER_MISSING`，不会因计划非空便发布 READY。Common 回归 60/60 PASS。
3. **不得在业务服务实现 `DurablePhysicalRecovery`、新写选主/Stage/ZK/签名/复制/READY。** 当前两个业务 Spring 配置仍指向 `orderCommonCertifiedPhysicalRecovery` 与 `tradeCommonCertifiedPhysicalRecovery`，而 Common 的统一生产物理恢复执行器仍缺少可运行、可信的装配。这是剩余生产阻塞，而不是 Demo+Common 的业务数据编解码缺陷。

## 未完成（严格 NO-GO）

- Common 必须提供真正**服务无关**的生产自动物理恢复执行器及统一入口，直接从自己的已打开原始 WAL/Custody、RSA、ZooKeeper、Snapshot/Manifest、恢复回执创建全部分区计划，并自行完成真实 RECOVERING→恢复→READY→物理角色安装。不得用无条件成功回调、Spring 空 Bean 或测试 RSA 代替，且需覆盖 256 分区同 JVM、多个互切周期。
- 本次 T498/T499 使用隔离 P090 的特定真实演示程序，**尚未**证明正式业务进程 256 分区全部可自动双向切换、每次回 Home、每次断连后不丢单/无重复、200 真实租户负载。
- E4 STRICT 模式故意 SIGKILL B 后，A 无双物理签名的下一条不得 ACK；**尚未完成**从这条物理未提交尾部继续进入 E5 并自动修复双方，再在严格模式继续完整新业务。
- 正式业务系统还需新租户注册→自动审批→Robot 报价/Tape 成交→订单、成交、资金、持仓及 Projection 检查，注入 Order/Trade A/B 故障后仍一致。未执行镜像替换，不得发布产品 GO。

**下一步只动 Common 生产恢复执行器、Demo Common 同一入口和真实故障验收；Order/Trade 只调整业务 `ReplicatedStateMachine` / byte[] 编解码。不得再增加业务侧 HA。**
