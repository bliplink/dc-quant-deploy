# T356｜Common 物理 READY 闭环 + 新 Epoch Watch 连续互切（2026-10-31）

> **阶段性 PASS：Common 代码 / 定向测试；真实 Docker 256 分区 A/B 全链仍 NO-GO。** 这是修复原有 Common 运行时的回调缺陷，**没有新选主器、没有业务专有 WAL，也没有新增独立 Recovery 服务**。

## 本轮代码与发现的关键运行时问题

1. `CommonCertifiedFailoverWatch` 从 T355 开始要求签名 READY 发布以后，必须调用 `requireInstalledAfterReady(Stage)` 确认真实节点物理恢复、业务 Snapshot+WAL replay 与本地 writer 已安装才把 Watch 标为完成；重启恢复路径不能因为 ZK 已 READY 就省略。
2. **本轮重新走业务节点调用链发现**：`CommonCertifiedNodeRuntime.armAutomaticFailoverWatch` 原来用 lambda 包装 `recoverAndPublish`；Java 8 接口新增的 `default requireInstalledAfterReady` 被这层 lambda 包装**悄悄丢弃**，因此 T355 的 Watch 直接测试不足以证明真实 Common node 安全。T356 新 Common commit `6fde0c5` 改为显式代理两个回调，保留对目标 Replica 的物理 WAL/socket 单分区关闭，再做 signed publisher 与 post-READY 的本地实际安装。
3. `CommonCertifiedNodeRuntime` 原来对每分区永久只允许一次 `armAutomaticFailoverWatch`，一轮切主完成后守护任务关闭、同进程的下轮 A/B 互切**无法重新挂 Watch**。T356 在原 Common node 内部允许安全轮换：仅前一轮完成签名 READY **并完成本地业务/物理安装**，且下一轮节点在更高 Epoch 以认证 Replica 角色运行时，才替换旧已完成 Watch。旧 Watch 未完成、仍是 Primary、还是相同 Epoch 均拒绝；原有监听器与其它健康分区不受影响。
4. 同时保留来自 T351/T354 的 `CommonCertifiedNodeRuntime.installCertifiedRecoveredPartition` 与 `installCertifiedRecoverySources`，新 Epoch Snapshot/WAL 回放仍由 **业务 byte[] 状态机**负责，Common 只判断已完成的合法恢复水位、控制面授权与物理证据。
5. 以上只是**Common 分区完成状态机、回调和复用权限**，不能替代 ZooKeeper 分区级旧 Primary 协作撤权、真实跨节点已提交水位屏障、签名 Stage→新 RSA RecoveryReceipt→READY 的独立证据。

## 本地代码与测试

| 项目 | 可核验事实 |
|---|---|
| Common `2bb029f` | READY CAS 后必须完成本地业务+物理恢复；即使 READY 已在 ZK 发布，重试只进行安装，不重复 CAS |
| Common `6fde0c5` | 正式 NodeRuntime 包装透传 post-READY 安装门禁；只有更新 Epoch 的认证 Replica 才可以重挂下一轮 Watch |
| T355 定向 | `CommonCertifiedFailoverCoordinatorTest 8/8` + `CommonCertifiedStrictCrashReadyCompletionTest 4/4` + `CommonCertifiedNodeRuntimeTest 14/14`，共 26/26 PASS |
| T356 定向 | `CommonCertifiedFailoverCoordinatorTest 9/9`，包含 wrapper 回调不丢失、READY 前无法重挂、READY 完成且同 Epoch 拒绝、高 Epoch 允许 |
| T355 全量 | 真实 T293 RSA、P193 只读证据，**153 suites / 662 tests / 0 failures / 0 errors / 6 skipped，Maven exit 0** |
| T356 最终全量 | **153 suites / 663 tests / 0 failures / 0 errors / 6 skipped，Maven exit 0**；真实原 P193 WAL 只读证据和历史 E4→E5 RSA 恢复用例通过 |
| Order / Trade 对新 Common JAR 的源码兼容 | 本地 Maven 安装 Common `6fde0c5` 后，Order **44 suites / 137 tests / 0 failures / 0 errors / 2 skipped**，Trade **52 suites / 207 tests / 0 failures / 0 errors / 0 skipped**；均 exit 0。不是 Docker 业务功能与真实 HA 已通过的证明。 |

## 真实 Order/Trade 替换仍然受限

- Order Spring `OrderCommonNodeRuntimeWiring` 只启用了 Common NodeBootstrap，没有绑定 `armAutomaticPhysicalRecoveryWatch` 的真实 `CommonCertifiedFailoverCoordinator`、持久化 StageLedger、旧主物理撤权、signed Snapshot/WAL replay、新 Epoch **两个实际恢复节点** RSA 回执 / STRICT READY，不能用人工 Spring `READY` 字符串替代。
- `OrderCommonRecoveringRuntimeWiring` 仍使用空 `Collections.emptyMap()` 恢复 handler，只能拒绝，不能完整恢复；Trade 也要用同一 Common 运行时接口，不允许各自增加选主。
- `CommonCertifiedFailoverCoordinator.stageRecovering` 仍要求旧 Primary **整节点 lease 消失**。B 在承担其他健康 128 个主分区时不能因为单个 P193 故障/需要归还 Home A，就杀整个 B 节点。缺少**同一 Common 内分区级、可持久核验的旧写入权限协作交接 + ACK 水位屏障**，这个问题必须解决以后才能声明 256 分区 Home 自动回切。
- 原始 P193 A=22667、B=22668（B 最末一条无双节点认证）WAL 不截断、不导入资金状态、不伪造签名。正式 `dc-saas-ordersvr[-b]` / `dc-saas-tradesvr[-b]` 仍旧 T335/T336 运行，Robot 停止；本轮没有替换它们，没有用 GitHub Actions。

**唯一最终验收：A/B 256 分区常态各 128 Primary + 128 Replica、单节点 SIGKILL 自动接管、恢复 Snapshot+WAL 后自动回 Home、双方反复互切、全部重新启动继续得到符合模式的真实持久 ACK、完成 Robot 盘口/Tape 与真实订单成交及订单/资金/持仓一致性。未达到前 NO-GO。**
