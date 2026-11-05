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

### T500｜完整 Common 候选 JAR 与业务全源码编译

首次打包 T497 JVM 运行时的候选 JAR 只包含 `CommonCertifiedNodeRuntime` 的变更，却遗漏了 T495 已提交的 `CommonCertifiedRecoveringBusinessFence` class；独立的 T495 专项测试此前通过，是因为测试 classpath 额外提供了该 class。**本轮通过真实业务全源码编译发现并修复这个打包问题**，没有恢复任何业务侧集群实现。

- 完整统一 Common 候选 `.work/t500-unified-common-package/common-t500-candidate.jar`，SHA-256 **`77ccd13419eb2fae94b1ae21d55a7eb8b05f9faa7cf3d2d165eddc7613556821`**；从 T497 候选加上 Common 内已提交的最终恢复凭证类，`javap` 可验证。
- Java 8 + Maven 本地依赖 + Lombok 1.18.34 注解处理器对 Order **123/123** 与 Trade **173/173** Java 主源码编译均成功（两服务不是单文件试编；且没有 GitHub Actions）。
- 用这份**完整 T500 JAR**重新执行原始业务物理两 RSA Snapshot + WAL suffix 回归：Order **1/1 PASS**，Trade **1/1 PASS**（包含恢复后真实业务编码/解析/幂等应用）。
- T497 A/B 双向 SIGKILL、T498/T499 E4 严格 ACK、T500 256 分区压力链路在之前 T497 核心物理代码 JAR 上实测；完整 T500 JAR 是增补缺失的 Common 业务恢复凭证类型，**不能把重新打包自动当成全部物理故障试验重测通过**。后续已经以完整 T500 构建物单独复跑故障和 256 分区压力，实测结果见下。

**完整打包统一候选 T500 JAR 的最终复测结果：**

- **真实 Demo A/B 两次 SIGKILL、双向追平和 B 重加入**：命令退出 **0**，日志 `.work/t500-unified-common-package/t500-full-jar-real-ababa.log`；原始 RSA 物理卷 `~/.opentradingcore/t124-live-kill-runs/20261105152132`。实际 A→B 恢复 40→60、A 回归追平、B→A 恢复写入 74、B 回归追平 74、A→B TCP 新写入后两端 85 / 7。E2/E3 单活客户 ACK 仍显式 LOCAL、RPO 风险不变。
- **真实双 JVM 256 分区严格物理压力重测**：命令退出 **0**，`.work/t500-unified-common-package/t500-full-jar-256-strict-load.log`，原始物理卷/完整 JSON 指标 `.work/t466-common-256-strict/20261105072402-77336/`。双方 256/256 分区字节一致、**540/540** 原始 WAL 帧一致，0 失败。200 档 A：**45.97 TPS、p95 155.366 ms、p99 189.462 ms**；B：**45.88 TPS、p95 162.733 ms、p99 212.426 ms**。这是**模拟租户**和共享 Mac Docker 资源，不是实际 200 SaaS 租户或生产性能承诺。
- **业务真实 RSA Snapshot+WAL suffix 回归**：同一 T500 完整 Common JAR，Order **1/1 PASS**、Trade **1/1 PASS**。
- **Order/Trade 全源码 Java 8 编译**：同一 JAR 加 Lombok 注解处理，**Order 123/123**、**Trade 173/173**。
- 本轮 T498/T499 实际在线 E3→E4 严格切换和两条 QUORUM 写入的历史实验依旧使用 T497 物理等价核心 JAR；**没有用完整 T500 JAR再次执行 T498/T499**，须保留清楚的证据边界。
- Common 生产统一物理恢复执行器仍未完成；真实 Order/Trade 启动自动恢复闭环 **NO-GO**。不要在这项门禁通过前部署候选镜像。

## T501–T503｜完整构建、Zero-suffix 恢复根因与正式 Common 修复（11 月 5 日）

- **T501 完整依赖门禁：** 已新增 `tests/check-common-order-trade-java8-compat.sh`，通过同一完整 Common JAR 编译 Order 的 123 个、Trade 的 173 个 Java 8 源文件；实际使用 Lombok 注解处理，确认恢复 fence 等关键类型真实打入 JAR，不以几个单测替代全量编译。GitHub 提交 `dc5be24d5c7513c4a2ec71908b862630f092a223`。
- **T502 Common 源码完整构建：** 直接从 **330 个 Common Java 源文件**编译并生成候选 JAR，SHA-256 `8b60f3abf0909a25fc885f8bbe07d7fe4aaddeb32614081b7a9d5b60c16a2b58`；Common 60/60 JUnit、Order 全源码、Trade 全源码兼容 PASS。该完整 JAR 上真实 Docker 三 ZK 双 SIGKILL A→B→A 与双方业务恢复、B 回归后 TCP 原始 WAL fsync 最终状态 85 / 7 亦退出 0，证据 `.work/t502-full-common-source-build/t502-real-ababa-full.log`。故障阶段客户 ACK 仍为 RPO 有风险的 LOCAL。
- **T503 根因：** 完整业务 Snapshot 水位与双节点认证提交 HEAD 完全相等（例如 seq=2）时，Netty 复制的后续原始 WAL 区间**长度为 0**，先前 `RecoveryQuorumWindowFromStaging.requireFullWindow` 仍要求在这个空区间中读到末条 WAL 帧，从而错误地抛 `source original WAL terminal not certified`，阻塞合法的业务恢复。
- **T503 修复（只在 Common）：** `VerifiedRecoveryStagingClient.Result` 对零尾段仅从已通过**两独立物理投票者 RPC**的认证 Prefix 取出*最后一条原始物理 WAL 帧 SHA*；每次重新读验持久 image、receipt、WAL SHA；严格绑定同一个已认证 `RecoveryRequest` 对象/partition/Epoch/HEAD/interval/hash；`RecoveryQuorumWindowFromStaging` 不合成新的帧，正常非空 WAL 依旧要求真实终止帧。后续 `CertifiedRecoverySourceAuthority` 还需**重新向实际两端投票者取回当前 HEAD、核对原始区间和赋权状态**，成功与否不直接发布 READY。
- **T503 负例：** 对 staging 原始 WAL 塞入多余字节会拒绝，伪造“字段相同但对象不同”的恢复请求拒绝，修改 transport receipt 或业务 Snapshot 仍拒绝；证书不足、被撤权与错误分区不得被空 WAL 特例绕过。
- **T503 代码已真正落 GitHub：** `bliplink/com.app.common` 的 `saas-crypto-latest` 一次原子提交 `ef3c3a133bff57bbd3488b16475b7e78f270d7b5`，涉及 6 个 Common Java 源文件、1 个新增 JUnit 实例，未改动 Order/Trade 集群代码。
- **T503 全源码验证：** 最新完整 Common JAR SHA-256 `78385b8448666ea739c8edcd915619578d91ae8a65209c11011aef20ce2ffd0b`，Common 330/330 源文件、Order 123/123、Trade 173/173 Java 8 编译 PASS；10 个 Common Test Class、**69/69 JUnit PASS**，其中签名 Snapshot@HEAD 无后续 WAL 的真实 Netty 集成测例及篡改负例 PASS。证据 `.work/t503-common-zero-suffix/t503-69-common-junit.log` 与 `.work/t503-common-zero-suffix/full-order-trade-compat`。
- **严格范围声明：** T503 定向 Netty Snapshot-at-HEAD 测试使用 HMAC 物理投票者测试凭据；另有真实双 RSA Common 物理 WAL/Custody 测试组合回归，但不能把该单例称为“线上 Order/Trade 256 分区严格完整 HA 通过”。Common 的生产自动恢复 `DurablePhysicalRecovery` 全链路仍未装配完成，Order/Trade 自动恢复/产品交易完整验收依旧 **NO-GO**。

### T504–T506 最终实测补充（2026-11-05）

**Common 代码提交：** `fa30022a583f3e11bebecb9ba2a3747154279e8c`（T504 全清单/RSA 物理工厂前置校验）；`4948c1c30dc1a4dc7f6c19a72c942307754d9926`（T505 后打开 WAL 通用工厂、T506 256 Primary/0 Replica Watch 安全布局）。部署仓库架构文档已同步记录这两个更改。

**最终可复现物理候选：** 完整 Common 330 源码编译 JAR SHA-256 `04364dd84ca84647bff7de5d4e90a33923d69a8b5872c50ddbb613538874b5e7`，同一 JAR 编译 Order 123、Trade 173 个 Java8 源文件全部 PASS；Common 10 组 **72/72 JUnit PASS**。新测试覆盖真实已打开的 B Replica 原始 WAL/custody 安全 factory 输入、未知旧主 RSA、最后一分区非法、129/127 动态 Home、256 全 Primary 但 0 个 Replica Watch。**256 全 Primary 测试属于结构/认证门禁，不是“B 宕机后 256 分区都可无损严格写入”的证明。**

| 最新 T506 真实隔离验收 | 结果与证据 |
|---|---|
| 三 ZK、A/B/C 独立物理 RSA、真实两次 SIGKILL | **PASS**；A→B 自动接管 40→60，A 重新加入追平，B→A 自动接管 60→74，B 返回追平，随后 A→B TCP 原始 WAL fsync 双方业务 **85/7**；`.work/t506-common-full-release/t506-real-ababa-full.log`，原始卷 `~/.opentradingcore/t124-live-kill-runs/20261105163611`。故障期客户 ACK 是有 RPO 风险的 **LOCAL**，不可冒充严格 ACK |
| 256 分区、两个真实 JVM 严格物理提交 | **PASS**；256/256 分区及 540/540 WAL 原始帧逐字节相同，10/50/200 模拟租户档位各零失败；`.work/t506-common-full-release/t506-256-real-strict-load.log`，物理度量 `.work/t466-common-256-strict/20261105083835-84654/metrics.json` |
| 模拟 200 租户档位 | A 200/200 ACK，**46.37 TPS**，p95 162.141 ms，p99 298.418 ms；B 200/200 ACK，**47.25 TPS**，p95 153.211 ms，p99 298.162 ms。共享 Mac Docker 资源下的测试负载，非 200 个真实 SaaS 租户 |
| Order 真实业务快照 + 签名 WAL 后缀 | **1/1 PASS**，`T494_ORDER_NONEMPTY_SIGNED_SNAPSHOT_PLUS_WAL_SUFFIX_REPLAY_PASS`；`.work/t506-common-full-release/t506-Order-business/test.log` |
| Trade 真实业务资金/持仓快照 + 签名 WAL 后缀 | **1/1 PASS**，`T494_TRADE_CERTIFIED_SNAPSHOT_PLUS_WAL_FUNDS_POSITIONS_PASS`；`.work/t506-common-full-release/t506-Trade-business/test.log` |
| Common 生产自动启动与物理恢复具体执行器 | **NO-GO（未完成）**：`tests/check-certified-auto-recovery-wiring.py` 当前两个 `orderCommonCertifiedPhysicalRecovery`、`tradeCommonCertifiedPhysicalRecovery` Bean producer 都为 0，严格 `--mode production` 检查仍 FAIL。T505 为 Common 通用启动及真实 WAL 后绑定能力，**还不是**整个生产执行器 |

原有运行中的 `otc-t488-order-a/b-ready`、`otc-t488-trade-a/b-ready` 及 Robot、Projection 容器均未替换或破坏；此处的真实 SIGKILL 只针对隔离 Common+Demo 容器。下一步必须由 Common 将完整的旧 Epoch 物理签名 Stage、独立 Replica 追平、原始 Snapshot/WAL 恢复、旧主撤权、第三方降级或严格双 RSA READY、以及恢复后角色安装封装为**一个可运行的通用物理执行器**，而不是 Order/Trade 的专属 Bean 或测试回调。

### T507–T508 补充：统一入口、真实 WAL 关闭验证

- T507：Order `06e9c42`、Trade `929bdb3` 已删除服务侧 `*CommonAutomaticReplicaPlans` Bean 和业务专属物理恢复 Qualifier；两者统一调用 `CommonCertifiedNodeBootstrap.openAndStartWithCertifiedAutomaticRecoveryFromOpenedPhysical`。Order 123 + Trade 173 Java 8 源码使用相同 T506 JAR 全量编译 PASS。
- 部署仓库提交 `847a40f` 更新 Common-only 自动 HA 启动门禁与 6 个反向测试；**业务边界 PASS，Common 生产执行器仍 NO-GO**。缺少真实执行器时不允许靠空 Spring Bean 或 fabricated READY 解锁。
- T508：Common `b3d1f66` 新增生产入口的**真实物理 OS-locked Replica WAL**启动负例。启动过程中先打开 B 的 WAL/Custody，绑定 Common 最终类型的认证 Source Handler，然后注入缺少全部恢复计划的工厂，证实拒绝 Netty 启动并关闭真实 WAL 锁；随即从相同物理目录重新开启 B Replica 成功。Common `CommonCertifiedNodeRuntimeTest` **16/16 PASS**。本项只证明错误路径没有句柄泄漏、没有伪造 READY 或客户 ACK，不证明生产自动 A/B 全部恢复。
- T506 原隔离 Demo A→B→A 双 SIGKILL、256 严格 WAL 比对以及 Order/Trade Snapshot + WAL 后缀的验证结果保持有效；当前业务运行容器未替换。

### T508｜最新 Common 候选的真实 E3→E4 STRICT 与故障拒写重验

**同一版 Common JAR：** `04364dd84ca84647bff7de5d4e90a33923d69a8b5872c50ddbb613538874b5e7`，对应 Common T505/T506 `4948c1c`；Common JUnit T508 新增真实启动负例 `b3d1f66`。

1. 基于同一天 T506 **真实两次 SIGKILL 后的 E3 物理 WAL** `~/.opentradingcore/t124-live-kill-runs/20261105163611`，独立 A/B JVM 各用原始 RSA 针对**完全相同的物理历史**重新签名 E4 Snapshot，重开双物理证据，业务总值 **85**、请求计数 **7**，新基线：`~/.opentradingcore/t508-e4-baseline-from-t506-20261105172820`。旧 T281 基线与当前 E3 历史不对应，首次试验由 Common SHA/成员摘要拒绝 `persisted original Genesis bytes/census differ`；改用正确的同一历史基线后通过，**没有**改代码、绕过认证或修改旧数据。
2. 真实三 ZK、在线 E3 A 主/B 备关闭原始 WAL/Netty、分别 RSA 签发旧 Epoch 退休证据，A/B 各自恢复 E4 并生成原始 RSA 恢复回执，最终发布**真实 E4 `STRICT_QUORUM READY`：PASS**。日志 `.work/t506-common-full-release/t508-e3-e4-strict-rearm-matched.log`，隔离证据卷 `~/.opentradingcore/t508-live-e3-to-e4-matched-20261105172842`。
3. 在这一个 E4 READY 上重启两个真实 JVM，实际完成新 E4 两条 Netty TCP 双 RSA、双 Custody fsync 客户提交，Replica WAL **seq=2**，客户返回 **`QUORUM_DURABLE`：PASS**；再 **SIGKILL B**，A 新写入因缺失物理 quorum 而拒绝伪造 ACK：**PASS**。日志 `.work/t506-common-full-release/t508-e4-new-strict-dual-ack-and-kill.log`。
4. 该完整组合证明最新 Common 在 Demo 隔离环境中**先容忍已声明 RPO 风险的 LOCAL 故障期，再安全切回双物理 STRICT** 的底层能力没有被 T504–T506 破坏。它**不是** Order/Trade 正式生产自动 HA 的 PASS：`CommonCertifiedProductionPhysicalRecovery` 完整执行器仍缺失，且 Spring 业务接线仅已切换到统一 Common Factory 接口，尚未完成真实自动化厂装配，正式验收仍 **NO-GO**。没有更换运行中的 `otc-t488-order/trade-a/b-ready` 容器。

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
