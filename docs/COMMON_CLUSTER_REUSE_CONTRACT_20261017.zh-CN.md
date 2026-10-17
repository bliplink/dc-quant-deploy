# Common / Trade / Order / MD 集群机制复用契约｜2026-10-17

## 目标与边界

这轮优先完成 **Trade-A / Trade-B 真实双向自动主切、自动恢复、真实物理 ACK 与业务一致性**，不是新增 SaaS 功能。Trade 通过后，Order A/B/C 按**同一 Common 集群协议**做自动故障切换，后续业务服务直接接入 Common 状态机接口。MD 复用 Common 的恢复框架，以行情业务自己的 Snapshot/Diff 模式实现；MD 仍从 Order 取得权威行情状态，Gateway 保持透传，不改 TLS 需求。

## 已实际落到 Common 的职责

1. `ReplicatedStateMachine`：通用 `apply(byte[])`、`snapshot(ChunkSink)`、`restore(ChunkSource)`、`finishReplay()`；业务快照必须完整且业务隔离，具体字节含义由 Trade/Order/MD 自己实现。
2. `StateMachineRecoveryCoordinator`、`VerifiedRecoveryStagingClient`、`DurableRecoveryInstallLedger`：独立分区恢复事务；按真实 Snapshot 基线与最新 committed WAL HEAD 下载、SHA/签名核验、旧 WAL 封存、完整持久化并保留未获得外部授权前的 NOT_READY。不得因只有一个成功 Source HEAD 就直接修改 Primary 角色。
3. `RecoverySourceAttestation`、`RecoverySnapshotManifestAttestation`、`RecoveryNodeSignature`：新挑战、真实源身份、当前 ZooKeeper epoch/version、物理 Snapshot/WAL HEAD 与公私钥验证，要求每个物理节点独立签名身份。
4. **本次新增 `RecoveryInstalledCommittedReplicaReceipt`**：面向任何服务的非零已提交 WAL **独立副本物理签名回执**，绑定随机 nonce、源/接收端身份、ZK version、Snapshot SHA/epoch、commit marker、committed state/head watermark；旧 epoch、其他节点、错误公钥、篡改及重放均拒绝。它仅证明接收端已独立签署源端指定的精确物理边界；**签名前的本地磁盘真实一致性证明和 READY/财务认证不因这一 Common API 自动完成**。

**源码事实**：Common `fix/common-asymmetric-recovery-node-identity-20261016@9eb6ae7bbadf22d4e59bb6b9f4a8d252fa572698`，`3.0.22-SNAPSHOT`，Mac 离线 Maven **318/318 PASS**。注意该完整身份基线还没有合并到 Common 旧的 `saas-crypto` 分支，不能只复制新单个类而缺少 `RecoveryNodeSignature` 和原有 Genesis 回执；后续统一发布必须整体合并完整 Common 基线。

## Trade 业务适配器与实机验证

Trade `saas-crypto@73f56ee8b1994445f34634f4773fa78e414da524`：
- `TradeRecoveryStateMachine` 实现 Common 分区业务状态机；Trade 自己处理资金、持仓、执行幂等、真实 Chronicle WAL、快照业务内容。
- `TradeRecoveredReplicaReceipt` 已缩为兼容适配器，所有签名协议与版本号委托 Common `RecoveryInstalledCommittedReplicaReceipt`；本地签收端仍独立核查 Common `REPLAY_COMPLETE` Ledger、物理 Snapshot 原始 SHA256、Chronicle 持久 head、真实 `STATE_COMMIT`。
- Common Jar `SHA256=018d0e9e9a92a6620192bdc8fa438fff540076d9de47a4f5c1b66ce91b59071f`；Trade 依赖此本地**未正式发布**的 `3.0.22-SNAPSHOT`，Mac 离线 Maven Trade **402/402 PASS**。GitHub Actions 不使用。
- Demo 已实际同步升级 Trade A/B `local/dc-saas-tradesvr:ab-common-physical-ack-402-20261017`（ARM64），两端实际 Common Jar hash 相同；Trade/Order 各 256 分区 READY；Trade A/B 各 128 Primary，两个容器 OOM=false/restart0，Order A/B/C 原镜像/容器未动。
- **未通过 HA 最终验收**：两端独立对称 RSA 恢复身份缺失，`autoWarm=false`；物理副本健康认证未启用，真实 ZK `replication-health=[]`、**0/256**。本次部署不会将“源码抽取成功”冒充 P090 A→B→A 连续 SIGKILL 自动追平与资金持仓审计通过。
- 受信身份配置之前通过执行环境安全检查被拦截，不得绕过。获得允许的安全身份配置后依 `docs/TRADE_P090_AUTOMATIC_REVERSAL_ACTIVATION.zh-CN.md` 启用 P090 pilot；真实物理 ACK/业务一致性过关后再开启 fleet。

## Order 为什么不能只更新 Common Jar 就宣布自动 HA

Order 当前有 Common Snapshot/WAL 边界校验，但它的业务日志、未成交委托、成交、撮合状态、幂等和 Projection watermark 不同于 Trade。接下来要确认/补齐 **Order 专属 `ReplicatedStateMachine` 业务适配器**、原始 WAL 安全恢复、实际物理 ACK 的本地真实性检查；**不得引用 Trade 类，也不得复制 Common 的签名协议实现**。

Order 需要直接复用 Common Source HEAD/Manifest、signed committed physical receipt、`DurableRecoveryInstallLedger` 和当前 ZK 证明；只有业务侧订单/执行与 Projection 一致性核验才由 Order 实现。Order-A/B/C 每一次自动晋升、恢复/追平与双主隔离都必须实机测试。之前的 256/256 READY/副本 snapshot 一致仅是预检，**不是 Order 真实故障切换通过**。

## MD 与未来服务

MD 业务实现自己的行情 `snapshot(bytes)` / `diff(bytes)` 及 Order 权威数据订阅，Common 承担 checkpoint/有序恢复/角色栅栏/发布隔离，不去解析行情，也不改 Gateway。新服务只需选择恢复模式、实现状态机接口及业务权威对账接口，不再重新发明 ZooKeeper 恢复、签名物理 ACK、Snapshot/WAL 传输和 Ledger。

## 统一正式验收门槛

1. **先真实 Trade**：带非零订单/成交/资金/持仓，A SIGKILL → B 交易正常 → A 自动下载/追平/独立 ACK → B SIGKILL → A 自动交易 → B 自动追平；反复双向且无丢单、无重复成交、无双主、对账一致。
2. **再 Order**：复用刚通过的 Common 机制，不重写复制协议，对 Order-A/B/C 执行实际 SIGKILL、恢复、副本追平/对账，再 10→50→200 租户压力和 2–3 倍 burst。
3. **最后收口发布**：将完整 Common 恢复基线合并到统一分支，正式发布新的不可变版本、`com.app.dc` 引用它、Order/Trade/MD 统一引用并验证部署。不要继续依赖局部 `3.0.22-SNAPSHOT` 私有 Jar 作为正式生产发行。
