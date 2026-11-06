# T524｜Common 生产自动 HA：256 分区当前 Epoch 恢复计划完整性门禁（2026-11-06）

## 结论：安全修复 PASS；真正自动 HA 仍 NO-GO

本轮仅修改 `bliplink/com.app.common` 的 `saas-crypto-latest`，未改 Order/Trade 业务源码，也未替换 T523 或 T488 Docker 运行容器。目标是纠正 Common 生产自动恢复执行器的明确旧 Epoch 误用风险，而不是通过虚假的 Spring Bean 或静态标记发布 READY。

### 真实发现的两个生产阻塞

1. T523 `automaticRecovery=true` 的 Trade B 启动实际因 `CommonCertifiedNodeBootstrap.CertifiedPhysicalRecoveryPlanFactory` Spring Bean 缺失而安全拒绝；相关现场日志保留 `~/.opentradingcore/t523-fresh-20261106-r1/trade-b-auto-pilot-nogo.log`。这是自动计划工厂装配未完成。
2. 已有 `CommonCertifiedProductionPhysicalRecovery` 虽实现该工厂接口，但 `evidence(...)` 仅接受当前 `epoch=1` 的 Replica；`bothSignedPhysicalReady(...)` 和业务安装也限定在 E1→E2。T523 当前是真实认证 `NPC1|2`，无法用旧 E1 installer 启动 E2→E3 自动恢复；需要 Common 层真实跨 Epoch 持久化安装。不能靠新增一个空 Bean 代替。

### T524 实际修改

- 在 `CommonCertifiedProductionPhysicalRecovery.verifiedPlans` 中，在任何局部分区的阶段/Watch 创建前，执行 `requireCurrentReplicaEpochInstallerCoverage`：必须对 P000–P255 的当前角色与 Epoch 完整确认，且本节点每个当前 Replica 必须有**同 Epoch**、此前在 Common 中重新验过物理 RSA/原始 WAL 的 installer 证明。
- 明确拒绝 E1 原始签名 installer 被当作当前 E2/E3 证据；也拒绝缺失 installer、缺分区和不属于该节点的 Replica。正常 256 主分区且 0 Replica 的节点不应被错误拒绝。
- 不创建新的业务日志、Watch、数据副本、READY 或 Epoch 协议。Order/Trade 没有新增集群代码。该修复是*生产前置安全验证*，并非正式 E2→E3 installer 的实现。

### 验证证据

- Java 8 生产类和测试类实编译：PASS。
- `CommonCertifiedProductionPhysicalRecoveryTest` 聚焦回归：**5/5 PASS**，包含当前 Epoch 过期证明拒绝、缺分区、错误角色、零 Replica 等。
- Common HA/WAL/Snapshot/跨 Epoch/双 RSA 完整相关回归：**109/109 PASS**，耗时约 145 秒，0 failure。
- 在 Mac 现场只读检查，`otc-t523-{order,trade}-{a,b}-hostready` 四个候选仍运行，未触发故障注入，T488 原环境未替换。

### 代码提交说明

- 干净本地 Common 工作树：`76c1e2b`，但直接 `git push` 受 Mac 访问 github.com:443 网络故障阻塞；**不可说该本地 commit 已推送**。
- 已改走已连接的 GitHub 连接器，按文件分别提交到远程 `bliplink/com.app.common` `saas-crypto-latest`：生产类提交 `3b7b2b4ff95555fe57b4e896b0f477691ec885eb`，对应测试提交 `22be5b9d5e87e31dd2ec151db87e37e80df8fed2`。这两次 API 提交并不等于本地 `76c1e2b` Git SHA。后续本地恢复网络后应 fetch/reconcile，**禁止强推**。

### 下一关（仍在 Common，先 Demo+Common）

1. 从真实当前 Epoch 的 OS-locked Replica WAL、持久提交证书及双 RSA Custody 读取受认证旧提交头；针对 E2→E3 在 Common 生成并安装有签名来源的 Snapshot + 原始 WAL 恢复计划，复用已有通用恢复接口，不用 E1 老收据冒充新 Epoch。
2. Common 自己提供服务无关的完整生产 `CertifiedPhysicalRecoveryPlanFactory`，在已认证物理分区打开之后装配 256 分区；Order/Trade 仍只提供 byte[]/Snapshot/Apply/Replay 业务接口。恢复后的 Home 回切仍必须满足最新 Epoch 和水位一致性。
3. 真实独立 JVM、三 ZK、SIGKILL A→B→A，验证旧主隔离、单节点明确持久化合同、自动追平、重复请求、业务一致性；**此项未通过之前，禁止将本轮声明为自动 HA PASS**。
4. Common Demo 验收完成后，用同一 Common JAR 执行 Order/Trade 候选替换、真实租户→Robot→订单成交→资金/持仓/Projection/MD 核验。不能让业务各自实现选主、Watch、恢复、READY。

当前状态：Common 当前 Epoch 错误恢复计划的强制拒绝已验证并提交；**工厂装配、E2→E3、自动双向切换及真实交易仍 NO-GO**。