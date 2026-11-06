# T525｜Common STRICT_QUORUM E2→E3 通用恢复入口与真实阻塞（2026-11-06）

## 结论

**Common 源码实现、Java 8 编译、HA 回归 PASS；生产自动双向 HA 和 Order/Trade 正式替换仍 NO-GO。** 本轮未修改 Order/Trade 的业务或集群逻辑，未触发正式容器 SIGKILL，未覆盖旧 T488/T523 数据。

### 根因：Demo E2 LOCAL 不能直接用于业务 E2 STRICT

- 当前 Common 的 `CommonCertifiedCrossEpochSurvivorInstall.installE3OpaqueV2` 针对 E1 STRICT → E2 `LOCAL_DURABLE_ASYNC` → E3，要求 B LOCAL 原始签名、A 独立追平签名，绝对不能把历史 LOCAL ACK 补记成双 RSA QUORUM ACK。
- 真正 T523 Order/Trade 的 256 个 E2 分区使用 `STRICT_QUORUM`，必须读取真正独立物理副本上旧 E2 的 **双 RSA WAL、CommitIndex、双份持久化 Custody**，再凭认证 ZK RECOVERING 阶段恢复并获得目标 E3 证明。单纯注入空 `CertifiedPhysicalRecoveryPlanFactory` 不会解决问题。

### T525 本轮 Common-only 代码

1. 新增 `CommonCertifiedStrictCrossEpochSurvivorInstall`：针对旧 E2 或更高 Epoch 的 STRICT RF2，先撤销旧的业务 replay READY，重新要求**同一 Common 协调器自身 RSA 签名账本**中的精确 ZK RECOVERING Stage、旧 EPOCH 2 物理 RSA 成员关系、严格 QUORUM 状态、真实幸存 Replica 持久化 CommitIndex/Custody 头。
2. 强制提供已经通过原始网络 RSA/HMAC 和 2 份持久化 quorum 检查的 `VerifiedRecoveryStagingClient.Result`。它的构造器是私有的，不能把随意复制来的快照、模拟 byte[]、裸 WAL 冒充可信恢复来源；其暂存结果会在实际安装时重新校验。
3. 复用 Common 既有 `CommonCertifiedSurvivorRecoveryAuthority`、`DurableRecoveryTransactionControl.forOpaqueCommittedWal`、`CommonCertifiedRecoveryInstall.installFromSurvivor`、业务 exclusive barrier 和 `DurableRecoveryInstallLedger`；不增加第二套状态机日志或签名机制。
4. `CommonCertifiedFailoverCoordinator.reopenSignedRecoveringPredecessor(stage)` 重新读取**本协调器自己的**原始 RSA Stage 并验证仍匹配实时 ZK；不接受另一份虽然 Epoch/Version 数字相同的外部 Stage Ledger。
5. 新增 `CommonCertifiedStrictCrossEpochSurvivorInstallTest`：STRICT E2→E3 结构前提、LOCAL/STRICT 混用、原始 Epoch 不符、提前 READY、伪造 stage 和非法快照 Head 的拒绝。该方法只安装业务数据，**不签发 READY/ACK/Primary**。

### 实际编译、回归

- 从 GitHub `bliplink/com.app.common` `saas-crypto-latest` T524 远程头 `22be5b9` 新建独立干净 worktree；未覆盖其他历史或未提交改动。
- **336/336 主 Java 源文件** Java 8 编译 PASS；**193/193 测试 Java 源文件** 编译 PASS。
- 最终完成 `CommonCertifiedFailoverCoordinator` 绑定修订后，共 **112/112 Common HA/WAL/Snapshot/跨 Epoch/RSA JUnit PASS**，耗时约 143 秒，0 failure；单独 T525 3/3 通过。
- 本地提交 `f92db25`。Mac 直连 `github.com:443` 失败无法推送该 SHA；已通过独立的 GitHub 连接器按路径写入远程 `saas-crypto-latest`，对应提交见下。**不得将本地提交 SHA 写成已远程推送的 SHA。**

远程实际提交：
- `bliplink/com.app.common` Common coordinator：`a57595785385563b88ce87425ad9e5aeaeb3dfc9`
- 新严格跨 Epoch 业务安装类：`50490a00c7b2bbf04473c1d4f47c58b1d4f8a0ce`
- 新 JUnit：`8e101618cc1d52edaacc541b5b191dd102773ca9`

### 真实物理数据现场核查

- 对 T523 原隔离 Docker 卷进行只读检查：Order A/B、Trade A/B 各持有 256 个 E2 `business.wal` 文件及 256 个 custody 目录/文件组。
- **四个物理节点均 0 个 `*.snapshot` 与 0 个 `.properties` 快照元数据文件**。这不是 READY 失败的证明，但说明本轮不能声称已经具备 E2 原始快照/全量业务恢复来源。应查明初始无成交 WAL HEAD、快照任务周期/拒绝原因并完成真实 E2 Snapshot 封存和原始网络预暂存。
- 当前 T523 正式启动设置 `automaticRecovery=false`；真实 `automaticRecovery=true` 在先前 T523 Pilot 报 Spring `CertifiedPhysicalRecoveryPlanFactory` 缺失。该 Bean 和包含 E2 持久化来源的 256 分区生产工厂本轮**尚未正式装配**。

### 后续不可跳过的步骤（全在 Common）

1. 在 Demo+Common 的 **E2 STRICT** 真实写入期间生成 Common 认证 Snapshot，向实际 A/B 物理 Replica 预暂存精确 SourceHead/Snapshot/原始 WAL + 两份独立 fsync Custody；不能在旧 Primary 断开后再向它请求原始快照。
2. Common 装配通用 `CertifiedPhysicalRecoveryPlanFactory`，对每个当前 Replica 注入已验证的真实 E2 installer 和 Common Watch；使用 T525 严格恢复入口完成 E2→E3。原始 Home 不变、Epoch 单调、旧主隔离，所有 256 分区完全认证后才能开放节点。
3. 目标 E3 STRICT READY 必须另外完成真实目标节点的独立 RSA Snapshot/恢复收据及两份物理安装证据；业务 replay PASS 不是 READY，LOCAL ACK 不能伪装成 QUORUM ACK。
4. Demo+Common 真实 A→B→A 连续 SIGKILL 和持续写入 PASS 后，用同一 Common JAR 构建替换 Order/Trade A/B；再做租户注册→Robot→订单成交→资金持仓和 Projection/MD 一致性。

**门禁状态：** Common 编译和单元回归 PASS；物理 E2 Snapshot/预暂存、生产工厂接线、E2→E3 真实故障切换、Order/Trade 交易 E2E **NO-GO**。不扩新功能，不在 Order/Trade 自建集群。