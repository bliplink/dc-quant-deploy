# T80｜Common 节点级真实物理证据恢复门禁（2026-10-24）

## 已完成

正式 `com.app.common`（分支 `saas-crypto`）本地提交 **`6829f47`**：新增 `CertifiedNodeRecoveryGate`，同时接入 `ZkNodeScopedControlPlane.useCertifiedPhysicalEvidence(...)`。同一个物理认证来源同时负责普通节点级 Manifest 变更，以及 ZK 多数派中断后的更高 Epoch 恢复授权。

- 严格模式必须经可注入的 **真实物理校验器** 核查：旧主无法继续写入；WAL/CommitIndex 与双 Custody 证明属于相同旧分区及旧 Epoch，已确认 WAL 序号与 SHA256 完全相同；两份签名属于先前的 Primary/Replica 成员，实际物理签名者必须独立。
- `LOCAL_DURABLE_ASYNC` 走独立的本地恢复认证，不能假装拥有2/2 QuorumDurable证书。恢复过程不接受未授权的严格/异步策略改变。
- 节点级授权检查本身不访问 ZooKeeper，实际认证只在控制面的新 Epoch / Manifest 变化时执行。所有 ZK CAS、会话所有权和租约退休校验仍由先前的节点级控制组件实施。
- **没有提供默认的假认证器**：真实签名 WAL/CommitIndex/双 Custody 认证来源没安装就不能产生新严格 READY。上述 Common gate **仅核对经注入验证器验证后返回的结果与身份、水位一致性**，不负责独立签名的实际密码学验证或物理fsync。

## 测试结果

在官方 Common 源码的 Mac Java 8 编译与JUnit测试中，本轮 **41/41项通过**（新增恢复门禁测试9项、控制适配回归和先前节点授权/撤权测试）。正向模拟证明覆盖256个分区（严格128、异步128）；拒绝双Custody与CommitIndex SHA或seq不一致、两个Custody相同物理签名者、签名者不属于旧Epoch的Primary/Replica、旧主未撤权、同一Epoch重复授权、无凭据的严格降级异步、无物理证据却进入新严格READY。还验证了 ZK 控制层中的门禁注册、拒绝不合格证明、合格模拟证明后允许继续执行控制授权。

**测试重要界限：** 本轮这些是 **Common接口与模拟物理证据提供者测试**，不是新一轮真实3ZK+2业务JVM物理故障实验。旧 T77/T79 的真实双JVM和3ZK测试不能当作本轮新门禁的真实验证。用户要求的真实Netty双WAL、持久化CommitIndex、独立Custody签名验证器尚未实现与此回调的最后接线。

尝试新增经物理证明后自动ZK CAS发布新Epoch控制事务时，该工具操作被执行环境安全检查**阻止**，这部分**没有落地、更没有执行**；未尝试绕过限制。本轮没有对Demo、ZooKeeper或生产数据执行新主切注入。

## 后续不可跳过的验收

1. 从隔离V19 RF2 `DemoV19Rf2StrictFailoverEvidence` 原有真实签名原始WAL/双Custody核验，以及 `DurableWalCommitIndex.verifiedHighestCertificate()`，创建适配 `CertifiedNodeRecoveryGate.PhysicalVerifier` 的实际物理证明器（当前正式Common尚未包含这些试点中的原始RF2类）；严格证书必须确切对应旧Epoch、旧主备物理身份与权威seq/SHA。
2. 在许可的执行环境中把认证结果接入独立、新Epoch ZooKeeper CAS授权事务；故障注入先验证多数派丢失→Grant到期503拒绝→多数派恢复→等待旧租约彻底失效、认证水位和旧主隔离→CAS新Epoch→两物理Custody READY→恢复交易。
3. 相同回归覆盖异步本地ACK、旧主恢复Learner追平、反向SIGKILL，之后再扩展实际256业务分区、10/50/200租户、资金/持仓/委托/成交/Projection一致性。
4. 严格与异步的最新**真实端到端 TPS 本轮没有重新测量**：T77严格32条组提交约105.7 WAL/s；异步逐条约97.2 WAL/s。不得报告为T80已优化达标。

## 交付与环境

- 正式Common本地Commit：`6829f47`，未推送、未发布 Maven、未运行 GitHub Actions。
- 完整变更源码及测试归档：`tests/patches/common-certified-physical-recovery-gate-t80-20261024.tar.gz`，对应SHA256清单。
- `dc-quant-deploy` 的正式Demo 24个 `dc-saas-*` 容器维持运行，未替换生产镜像、不删任何WAL或历史数据。
- **T80 公共恢复校验单元测试 PASS；真实 ZK 自动切换/完整物理HA仍 NO-GO。**
