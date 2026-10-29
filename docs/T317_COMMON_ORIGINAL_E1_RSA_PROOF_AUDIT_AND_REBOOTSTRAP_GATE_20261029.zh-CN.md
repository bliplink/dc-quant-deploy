# T317｜原始真实 E1 双 RSA 全链路凭据只读审计

日期：2026-10-29。范围：现有 Common/Order/Trade 不增加机制、不修改任何原业务/创世 WAL、不改正在运行的 `dc-saas-*`、不使用 GitHub Actions。测试仅从 Mac 本地原始 T181 磁盘、只读 RSA 公钥载入，并调用已实现的 Common 正式认证 API；无自制成功证书。

## 真实审计结果

1. 原始物理目录 `~/.opentradingcore/dc-saas-runtime-clean-20261016/data/common-t181-born` 及已有可信 RSA 公钥目录 `/.../v19-quorum-secrets/public` 仍存在。`OrderSvr`、`TradeSvr` 的 `sealed/P000..P255` 各包含 `genesis-e1.snapshot` 和 `genesis-e1.quorum`。
2. 用现行 `CommonCertifiedGenesisQuorum.reopen()` 及原始物理节点 `MacDockerSlotA/B`、RSA2048 原公钥 `CommonHaDemoA/B` 对 **512 份原始 E1 双签名 Genesis** 全量验证，结果：Order **256/256 PASS**，Trade **256/256 PASS**；每个服务均有原始 A Primary 128 分区、B Primary 128 分区，哈希与原先配置物理成员完全匹配。
3. 对同一 512 分区，在**旧确切命名空间** `/otc/demo-t181-fresh-20261027/{order,trade}` 上用 `CommonOriginalE1ZeroAckBirthEvidence.requireOriginalPhysicalZeroAckWal` 验证双原始投票者各自出生时 RSA 签名、独立业务 WAL birth 根目录只有该签名文件。Order **512/512 原始投票者 PASS**，Trade **512/512 PASS**；共 1,024 个零 ACK 签名出生凭据，无 WAL 文件被更改。
4. 读取 Order 与 Trade 的 `first-ready/e1-to-e2-A.signed` 原始 557 字节票据，按正式签名格式检查字节长度/256 字节 RSA 签名，用原始 A 公钥 SHA256withRSA 验签：**Order PASS、Trade PASS**，票据明确绑定旧 T181 命名空间，不是新租户或新 ZK 命名空间的 READY 许可。
5. 负向实际测试：尝试用 T181 中真实有效的原始 Genesis/零 ACK birth 声明 T316 **新命名空间** `/otc/t316-20261029/{order,trade}` 的身份；`CommonOriginalE1ZeroAckBirthEvidence` 对两个服务各自 P000 的双 RSA 凭据均拒绝，明确报 `original zero-head birth namespace/Genesis changed`，**4/4 正确拒绝**。没有绕过或重签老 WAL。

## 具体剩余阻塞（不是新集群功能）

现有 T181 一键部署的 `common-t181-firstboot/OrderSvrA.properties` 和 `TradeSvrA.properties` 仍采用 `nodeRuntime.provisionOriginalBirth=true`，**没有**新 Common `CommonOriginalE1VerifiedSourceConfig` 所要求的每一分区 `freshE1.P000..P255.*` 原始成员、双 RSA 原始 WAL/交易根目录映射，也没有在 `RECOVERING` 启动时开启新版 `inspectFencedBusiness`、`installFencedFreshGenesis`、`stageOriginalFleet` 真实签名阶段。因此直接复用旧部署配置无法在 T316 新命名空间完成 E1 Genesis、双原始复放、256 分区签名 `RECOVERING`→首次 E2 `READY`。本轮没有猜测/填造物理凭据来让 READY 变绿。

**下一步严格执行已存在的 Common 接口**：使用新隔离节点、新命名空间和真正由业务状态机快照捕获、双节点独立 fsync 与 RSA 签署的新 256 分区原始 Genesis/零 ACK 凭据，建立符合 `CommonOriginalE1LiveInstaller` / `CommonOriginalE1FleetFirstActivationStage` / `CommonOriginalE1FirstReadyActivation` 的初始签名控制面，才可让 Order/Trade 自动启动并进入 READY。它必须复用 Demo+Common，同一公共实现；Order/Trade 仅提供业务状态机 `byte[]`。再做真实租户→Robot→盘口/Tape/成交、自动 A↔B 切换一致性验收。当前业务 GO **仍 NO-GO**。

实测 Java 验证程序只暂存在 Mac `/tmp/T317GenesisAudit.java`、`/tmp/T317ZeroBirthAudit.java`、`/tmp/T317ReadyTicketAudit.java`、`/tmp/T317NoCertificateReuse.java`，未混入任何业务镜像或新增公共生产接口。
