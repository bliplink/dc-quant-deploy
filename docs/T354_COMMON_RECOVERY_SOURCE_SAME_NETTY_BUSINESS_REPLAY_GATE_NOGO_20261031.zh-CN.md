# T354｜Common 同一 Netty 按分区安装认证 Snapshot/WAL 恢复源（2026-10-31）

> **状态：Common 代码/定向测试通过；正式 Order/Trade 自动接管、自动回 Home 和真实交易仍 NO-GO。** 遵循 `COMMON_AB_HOME_PRIMARY_AUTO_FAILBACK_ARCHITECTURE_20261031.zh-CN.md`。

## 本轮查明的真实接线缺口

1. Order `OrderCommonNodeRuntimeWiring` 可以调用 Common `CommonCertifiedNodeBootstrap.openAndStartWithZkFencingAndReplay`，却**没有**启动 `CommonCertifiedNodeRuntime.armAutomaticFailoverWatch`，也没有提供原始签名 Stage、快照/WAL 恢复和两物理节点完成回执的自动发布回调。Order `OrderCommonRecoveringRuntimeWiring` 将 `Collections.emptyMap()` 传给 `CommonRecoveringNodeRuntime.openAndStart`，该模式只能拒绝业务并启动空的恢复 RPC。仅镜像重启不会自己完成自动主切。
2. 旧 Common `CommonCertifiedRecoverySourceRouter` 只允许构造时指定认证恢复来源；单个分区发生角色变更后，无法在不重启整节点的情况下增加新的签名恢复处理器。
3. 上轮 `171eee4` 完成分区新 Epoch 运行时原位替换，但未再次要求业务状态已完成恢复回放。签名物理授权并不代表资金/持仓/委托业务状态可用。

## Common 唯一路径的最小修改

- `68c270e`：`CommonCertifiedNodeRuntime.installCertifiedRecoveredPartition(..., CommonBusinessRecoveryReadiness)` 必须在更换任何物理句柄、路由或写入器前验证已有通用业务 Snapshot/WAL 回放完成门禁。null 或明确拒绝的业务证明均不能使 Replica 变为 Primary。
- `631d144`：`CommonCertifiedRecoverySourceRouter.installCertifiedSources` 及 `CommonCertifiedNodeRuntime.installCertifiedRecoverySources` 在**原已启动的一个 Netty TCP listener** 上对目标分区以 copy-on-write 安装原有 Common 已签名 `RecoverySourceHead/Manifest/Data/DurablePrefix` 控制处理器。必须同时满足当前 Common 物理角色、业务恢复门禁、处理器最终类型和源节点主备约束；禁止 lambda 假成功和重复覆盖。
- 原有 `replaceCertified` 在分区 Epoch 更换时**撤销旧分区全部签名来源处理器**，必须显式重新认证安装新来源。无第二套 HA，没有 Gateway 改造，没有 ZK WAL 热路径。
- `CommonCertifiedNodeRuntimeTest` 使用原 Demo RSA 身份和共享 Netty 监听验证同 Epoch 拒绝、业务未追平拒绝、未签名处理器拒绝、重复注册拒绝，以及新 Epoch 目标 Primary 成功挂入同一个端口。定向 **14/14 PASS**。测试控制面使用合成 Epoch grant，**并非真实 ZooKeeper CAS 自动接管**。
- 完整 Common Maven（带 T293 真实 E4→E5 RSA + T330 原始 P193 只读证据）：**153 suites / 661 tests / 0 failures / 0 errors / 6 skipped，最终 exit 0**。首次并发的旧 Maven 测试曾因同一 `target/` 类文件竞争造成 P193 `NoClassDefFoundError`；**后一次不重叠的完整回归通过**，且 P193 单项重新为 1/1 PASS。不可把并发失败误记为业务 WAL 一致性错误。
- 本地 Maven 安装同一 Common JAR 后，Order **44 suites / 137 tests / 0 failures / 0 errors / 2 skipped**，Trade **52 suites / 207 tests / 0 failures / 0 errors / 0 skipped**；均 exit 0。两项 Order skipped 仍需在真实证据可用环境单独验收。上述仅证明本地源码兼容，不代表 Docker 交易及自动 HA 已经 PASS。

## 下一轮必须完成而尚未完成

- **仅一条** Common 自动生命周期：保留已有 ZooKeeper 授权及单向 Netty WAL；补齐分区级真实旧主隔离/签名 Stage、完整旧 CommitIndex 双签提交前缀、Snapshot+WAL 追平、业务状态回放、双真实物理节点恢复回执、E(n+1) READY、Common Watch 连续自动接管。
- 自动 Home 回切不是“自动抢主”：现任节点仍在线，必须完成**分区级合作撤权和已提交水位屏障**，才能 CAS 移交给已追平的 Home；不能依赖整节点 lease 消失、不能人为杀整个 B 节点导致 B 原有 128 主分区受影响。
- 必须真实测试 A/B 正常 128 主+128 备、A SIGKILL B 256 接管、A 恢复自动回 Home、B 反向同理、全量重启后严格 ACK/明确本地降级 RPO、订单与资金一致。
- **直到真实 Common 自动 HA 与业务验收 PASS，正式 dc-saas-ordersvr[-b] T335 / dc-saas-tradesvr[-b] T336 维持旧镜像，Robot 暂未恢复。** 原始 P193 A22667/B22668 额外 B 无双签尾部完整保留，不做假 READY、未签 WAL 导入或修改旧数据。

**当前结果 NO-GO，不调用 GitHub Actions，不改变在线 Order/Trade。**
