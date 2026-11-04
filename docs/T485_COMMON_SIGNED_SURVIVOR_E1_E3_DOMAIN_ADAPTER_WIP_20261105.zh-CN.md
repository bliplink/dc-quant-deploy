# T485｜Common 签名 E1/E3 离线幸存者恢复与 Order/Trade 业务状态机接线｜WIP / NO-GO

**日期：2026-11-05。当前为本地未验证代码候选，不是已发布服务，也不满足业务 HA GO。**

## 为什么不能把“补一个 Bean”当作最终修复

1. T483 Common Watch 原 Home 双向接管的确定性测试、134/134 回归和隔离 Demo A→B→A 两次 SIGKILL 已 PASS，但 **只是 Common/Demo 测试版本**。
2. `OrderCommonAutomaticRecoveryDependenciesWiring` 与 `TradeCommonAutomaticRecoveryDependenciesWiring` 对 `DurablePhysicalRecovery` 有强制依赖，至今仍无可核验的正式生产提供者；没有办法安全地直接替换业务镜像。
3. 正式的 `CommonSignedReplayHandoffProof` 要求旧 Epoch 两独立 RSA Custody/CommitIndex、物理 Old Owner 撤权及真实已加载的最终业务状态。Order/Trade `*CommonRecoveredDomainWiring` 仍硬编码 E1/seq0 的 serving snapshot readback；Trade 的 `TradeRecoveryApplier.verifyAssignment` 在普通模式要求分区已经 routable，专门的 fenced adapter 又只允许 E1 空状态，**因此 E2/E3 非空数据在 RECOVERING 中仍不能实际提交安装**。
4. Demo 已有两个真正的 Common 物理恢复安装器：`CommonCertifiedGenesisSurvivorInstall.install`（A SIGKILL、从 B 的原始 E1 A+B 签名 Genesis/WAL/Custody恢复）及 `CommonCertifiedCrossEpochSurvivorInstall.installE3`（E1 严格原始 WAL + E2 B LOCAL WAL + 已独立 fsync 的 A 镜像 + 证书）；它们不会签发 READY、不会重写原始 WAL。这才是 Order/Trade 应当调用的机制。

## 本轮本地候选代码（还未通过测试，未提交业务分支）

Common:
- `CommonCertifiedSurvivorRecoveryAuthority.exactPinnedRequest`，返回真实原始签名 Authority 所固定的请求身份；仅是身份访问器，不授予 READY。
- `CommonCertifiedNodeBootstrap.prepareCertifiedOpaqueSurvivorBeforeReady`，严格使用 Common 原有 `installFromSurvivor`，仍要求真实认证 Stage/Authority/独占恢复锁/持久 ledger，失败先撤销 replay。
- `CommonCertifiedGenesisSurvivorInstall.install` 新增保持原接口兼容的 `Function<RecoveryRequest,PartitionStateMachineRegistry>` 工厂重载，使业务状态机只能在 Common 验证原始 B WAL/Genesis 并构造请求后实例化。
- `CommonCertifiedCrossEpochSurvivorInstall.installE3` 同样新增工厂重载，仍由 Common 校验 E1 与 E2 原始物理 WAL、独立新副本 fsync 以及 E3 RECOVERING。

Order:
- `OrderCommonRecoveryBinding` 新增直接复用 Common 上述 E1/E3 离线安装器的业务薄适配，不新增服务私有 ZK、WAL、选主或 READY。
- `OrderRecoveryStateMachine` 对原始 Epoch 内物理序号和 Common 跨 Epoch 连续**逻辑序号**分别校验，只在认证的 E1→E2 双 Epoch v1 路径允许物理序号由 N 重置到 1；原始 Wire 不修改。

Trade:
- `TradeCommonRecoveryBinding` 对上述两个离线 Common 安装器提供薄适配。
- `TradeRecoveryStateMachine` 类似地验证原始 Epoch/序号重置，将通过校验的全局逻辑序号用于业务恢复计划，不修改原始 `TradeJournalRecord`。

上述共 8 个文件保存在 Mac `/Users/kong/dc-quant-deploy/.work/` 下对应 `t472-common-publish-20261104`、`t444-order-stream`、`t452-trade-windowed-e2` 的未提交工作树。各源码 `git diff --check` 在修改当时没有报告 whitespace 错误。

## 本轮阻断

尝试 Java8 全部相关源码编译时，WebCodex 实际返回 `此工具调用被 OpenAI 的安全检查屏蔽`；之后一次只读的 Trade 恢复门禁源码检查也被拦截。**没有通过其他执行方式绕过，未运行 JUnit 或真实容器验收，未推送未编译候选到正式业务分支**。

T484 的逐分区 Common Writer/Source 修复仍只证明了 RED，GREEN 未完成。T483 134/134、Demo 双 SIGKILL、256/256 WAL 不能冒充 T484/T485 新代码的结果。

## 接下来正确的关键路径（不得降级认证）

1. 在获准的执行环境中对这 8 个候选类运行 Java8 全量编译；先检查跨 Epoch `RecoveryRequest` 所载 Genesis 业务元数据与实际带 A/B 签名的 Snapshot 是否精确一致，不要伪造 metadata。
2. 将 Trade 的业务 apply 移入**Common 确切签名的 RECOVERING 分区独占事务**。普通 routable gate 继续拒绝非 READY；只能调用 Common 实时 `requireCurrentRecoveringStage` / 旧主签名 Stage 并由 Common 控制是否仍授权安装，不能用随意布尔值绕过 Trade 检查。
3. Order/Trade 的服务上层 Spring 真正绑定已签名的 B 原始 WAL/Custody、独立 C 见证、E2 LOCAL ACK 和 E3 A 追平/反向切换；剔除 E1-zero-only readback 限制时必须引入**实际已加载业务状态和签名 WAL 最终 HEAD 的可重复一致性验收**，不能简单删除校验。
4. 同版跑 T484 GREEN、Common 全回归、Order/Trade 业务非空 E1/E2/E3 状态恢复、Demo 双次 SIGKILL、256 分区严格复制；全部通过才构建/替换正式业务服务并用新租户 Robot/Tape 真实成交，检查 orders/executions/balances/positions/Projection，进行两次真实业务 SIGKILL。
5. 故障期间第三见证授权的 `LOCAL_DURABLE_ASYNC` **明确有 RPO 风险，不等于严格 2/2 ACK/RPO0**。不应假签离线节点，也不应将其提交为严格双节点 READY。

**GO 状态：NO-GO。四个旧 Order/Trade 运行容器和数据未被此轮操作修改。**