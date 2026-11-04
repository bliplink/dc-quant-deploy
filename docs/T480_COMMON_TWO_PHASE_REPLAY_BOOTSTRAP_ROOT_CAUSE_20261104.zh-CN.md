# T480｜Demo+Common 与 Order/Trade 自动恢复接线差异：双阶段启动根因（2026-11-04）

**结论：不是缺少新的集群机制，而是 Common 初始化与正式业务恢复之间存在明确的启动时序缺口。** 本轮有源码对照和可重复 JUnit 证据；**尚未实现最终修复、未重新部署业务服务、Order/Trade E2/E3 仍 NO-GO**。

## 已验证的精确代码根因

1. `CommonCertifiedNodeBootstrap.openAndStartWithCertifiedAutomaticRecoveryFromPhysicalSources` **在打开物理 WAL 前**即调用 `attestedBusinessReplay.requireBusinessRecoveryReady(service,node)`。内部 `openAndStart(...)` 对业务回放还有一次 pre-open check，然后在 Netty bind 前再检查。这对已经恢复好的 Demo 成立，但对需要先取得物理 WAL/Snapshot 来完成回放的 E2/E3 正式业务，形成先后循环。
2. 代码复现 JUnit `CommonPreOpenReplayDependencyTest`：使用不提供 READY 的业务回放验证器，调用原 Common 启动入口，实际先命中 `EXACT_DOMAIN_REPLAY_NOT_INSTALLED`，未打开物理资源。**1/1 PASS**。源码已提交 `bliplink/com.app.common/saas-crypto-latest`：commit `f22a94d897e8186a3bc4bbb9efaee6ee23c99628`。
3. Order/Trade 的 `*CommonRecoveringRuntimeWiring` 在 `phase=RECOVERING` 时启动 `CommonRecoveringNodeRuntime.openAndStart(...,Collections.emptyMap(),...)`。它使用真正 ZK 会话、RSA 和非业务 Netty 控制端点，但没有可执行的 signed Source Handler / Replica 安装回调，绝不提供正式业务 READY。
4. `*CommonAutomaticRecoveryDependenciesWiring` 在 `phase=READY` 时才生效，并通过 `@Qualifier("orderCommonCertifiedPhysicalRecovery")` / `@Qualifier("tradeCommonCertifiedPhysicalRecovery")` 请求 `DurablePhysicalRecovery`。当前业务分支尚无真正注册的生产 Bean。已有 `CommonCertifiedAutomaticReplicaPlanWiring` 需要四项真实证明，而不是一个名字或测试回调。
5. `CommonCertifiedNodeBootstrap.openAndStart(...)` 在物理打开时还拒绝任何非 Routable/ZK RECOVERING 分区。这符合防止交易错误写入，但意味着未来不能仅删除前置回放检查就宣称具备恢复能力。

以上代码路径与已发布 `saas-crypto-latest` 远端逐一比对，非仅依赖本地脏工作树。尤其是前置 Common 检查、RECOVERING 的空 Handler、READY 才创建 Signed Source 和缺失的物理恢复执行者四个事实同时存在。

## 唯一合理的实现边界（不能削弱认证）

**Common 中统一一个两阶段初始化流程，Demo、Order、Trade 使用相同入口；业务只提供 byte[] Snapshot/Restore/Apply、真实 RSA/ZK/落盘目录等配置。**

1. **PREPARE（绝不对客户开放）**：真实 ZooKeeper 控制、物理分区及 old-Epoch RSA/Custody/CommitIndex/Snapshot/WAL 可验证引用，不创建可路由 Primary Writer/客户端 ACK。不允许伪造已经通过的业务 Replay/READY。
2. **INSTALL（同一 Common 恢复器）**：使用已验收的 `VerifiedRecoveryStagingClient`、`CertifiedRecoverySourceAuthority`、`CommonCertifiedRecoveryInstall` 和 `DurableRecoveryInstallLedger`，对每一个恢复分区实际 Snapshot Restore + 原始 WAL Apply + fsync/二次物理证据校验。非空历史 E1→E2→E3 必须做证据链校验，不能接受空 E1 Genesis 代替。
3. **ACTIVATE（必须重新核验）**：只有旧主真实撤权、两个独立物理 voter RSA / CommitIndex / Custody、业务恢复水位和真实 signed READY 都满足时，才发布 ZK READY、启用 Netty 业务监听及每个恢复完成的 Pxxx Writer。其他已认证健康分区不因单分区恢复而被全节点拒绝。
4. **Spring 极薄接线**：Order/Trade 只提供 `ReplicatedStateMachine`、持久目录和原有信任配置；不能在业务代码中新增 election, Watch, Epoch 或 WAL；Common 真正安装恢复证据，不依赖业务返回“成功”布尔值。
5. **验收**：先用真实 Demo A/B 非空 Snapshot+多 Epoch WAL 测一次以上过程，再将相同 Common JAR 与初始化入口用于 Order/Trade。必须完成 256 分区/128:128 Home 恢复，真实新租户 Robot 持续下单/成交，在交易中真实 SIGKILL A→B→A，最后资金/持仓/订单/成交/Projection 一致性。

## 本轮安全及实际状态

- 新增的上述 Common 启动顺序测试 1/1 PASS，测试源码推送成功。
- 尝试直接修改 `CommonCertifiedAutomaticSourceWiring` 以集中 Spring 之后的 Source Handler 生产工厂时，远程执行环境安全检查拒绝；**该源码修改没有成功，不能宣称修复已落地**。
- 当前运行 Order/Trade 容器保持不变，没有替换镜像、清理 WAL/数据或手工重置旧 Epoch。没有使用 GitHub Actions。
- 当前产品完整业务 HA、Robot 点价成交及业务自动双向故障切换仍 **NO-GO**。

**下一轮正确工作是实际完成上述 Common 两阶段安装，不是创建一个仅返回非空对象的 Spring Bean。**
