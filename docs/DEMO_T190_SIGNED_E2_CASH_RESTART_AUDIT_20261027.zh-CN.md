# T190｜真实 CashIn Common WAL 与 E2 热数据副本重启阻塞审计

2026-10-27，Mac Mini Demo，saas-crypto，仅本地 ARM64 构建、无 GitHub Actions。

## 已验证证据（不是完整 HA PASS）
- T190 Trade 镜像完整 Java 8 源码编译通过；TradeCertifiedCashInAdmissionTest 3/3 JUnit PASS。
- CashIn 不再调用旧 executeMutation 先改余额，而是准备 ACCOUNT_BALANCE + POSTING after-state；Common commitThenApply 在物理提交后才变更真实余额及 MySQL 投影。
- 新隔离租户 R0F6CC：三个账户（robotmaker、robottrader、robottape）各有 1,000,000 Demo 资金及独立 E2CASH- 幂等主键流水；恰好 3 条。
- Trade A/B 的 P246/epoch-2/business.wal 各 4511 字节；SHA-256 均为 8d3f4bf62245669ff627e9d14f75a00a636e92e3671ebc7fdf896e7f53bb58b5。
- tests/T190ReadOnlyWalProof.java：只读 WAL、原始 pinned A/B public keys、Common DurableWalCertificateCustody 验证 E2 configVersion=2 / seq=3 / 2/2 RSA 提交签名。
- tests/t190_readonly_cash_wal_projection_audit.py：解码三笔 STATE_BATCH，逐条核对真实 DB posting 唯一主键、request_id、金额和三用户最终余额。
- 两项检查只读；不重签、不 ACK、不清理 WAL。

## 当前阻塞（NO-GO）
- Trade A T190 正常启动；Trade B T190 Exited (1)。CommonCertifiedPartitionRuntime.java 的 E2 virgin replica 准入要求 forcedSequence()==0，B 已有 3 笔真实签名提交，因而拒绝空副本初始化。
- Robot R0F6CC / e2e-depth10 配置 enabled=1，但 runtime_status=ERROR；盘口、委托、撮合和自动互切均未验收通过。
- A/B WAL 哈希相同及双 RSA quorum 可信，仅证明提交一致；不代表 JVM 的 Trade 余额、持仓和交易业务状态已重放，不授权业务 READY。
- 保留原始 WAL 与证书；不可绕过拒绝、不可重新签历史证明，不向旧请求重复入金。

## 下一关唯一正确入口
1. Common 统一实现 E2 非空冷启动 / Replica 追平：验当前 Manifest 与租约、同一物理 WAL、真实 2/2 signed custody 与 CommitIndex 水位；任何不符 fail-closed。
2. Common 将仅有签名认证的 WAL 原始 bytes 送业务 ReplicatedStateMachine / TradeRecoveryApplier，在隔离 staged state 完成回放，校验余额、持仓、委托、成交、资金流水和 Projection，方可 READY。
3. 检查 B 真正可用、P246 历史账户一致、256 分区全部授权；再执行 Robot 真实挂单成交及 SIGKILL A/B 自动切换。
4. 本地编译/提交全部服务，继续禁用 GitHub Actions。

复核：先运行 T190ReadOnlyWalProof，再运行 tests/t190_readonly_cash_wal_projection_audit.py。它们不能替代 Common 的运行时授权。
