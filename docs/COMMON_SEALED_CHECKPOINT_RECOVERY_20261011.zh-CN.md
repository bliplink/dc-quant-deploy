# 2026-10-11 Common HA：不可变快照封存与 Order/Trade 恢复集成

## 目的和根本修复

统一 HA 的业务状态机：**Common 负责恢复机制，Order/Trade 实现 `apply(byte[])`、`snapshot(ChunkSink)`、`restore(ChunkSource)`**。恢复事务必须保证 **已校验快照 == 已持久化 checkpoint 指向的镜像 == 真正被业务 restore 的镜像**。之前的 `Control.persistVerifiedCheckpoint(RecoveryRequest)` 是 void，业务仍使用原始暂存路径恢复：原始文件如果被替换，便有 SHA A / 恢复 B 的潜在时间竞态。

本次已更改 Common `StateMachineRecoveryCoordinator.Control.persistVerifiedCheckpoint` 返回 **`java.nio.file.Path`**，并禁止把原始暂存路径作为持久 checkpoint 路径返回。Coordinator 先校验 inbound，再要求源端权威证明，调用 checkpoint 持久化，最后**只从业务返回的封存文件**再次校验并执行 `restore`，之后才调用已证明提交的 `CommittedLogSource` 做连续增量 `apply`。恢复结束时仍不会擅自把节点设为 READY。

新增 Common `DurableRecoverySnapshotSeal`：
- 验证分区 ID、snapshot epoch/seq、提交状态水位与 SHA-256；拒绝符号链接输入、已存在但元数据不同或文件校验不一致的旧镜像。
- `64KiB` 缓冲分块复制、完整计算封存文件 SHA-256，文件 `FileChannel.force(true)`，`ATOMIC_MOVE` 原子提交快照和 metadata（没有原子移动支持则失败关闭），对父目录 fsync；过程不把 50MiB+ 的 Trade 快照复制进整个 Java 堆。
- 元数据包含格式、partition、snapshotEpoch/seq、committedStateSeq/epoch、commitMarkerSeq、SHA-256；重复 seal 同一文件需校验完整 manifest/image。坏 SHA、坏 metadata、超限、缺少完整 checkpoint 都拒绝。
- 两阶段 **image + metadata** 的 crash 检查：只有镜像和元数据都存在并通过 SHA 校验时才是有效封存文件；不具有权威来源或 durable journal baseline 的文件**不能**成为可 READY 的业务状态。
- 独立的测试故意在 `seal()` 返回之后破坏 inbound 文件，Common 仍只从封存版本恢复；如业务错误地返回 inbound 路径则拒绝且业务回调不执行。

## Order/Trade 跨模块验收

- **Order**：`OrderCommonRecoveryCoordinatorIntegrationTest` 使用真实 Chronicle Queue `STATE_UPSERT` + `STATE_COMMIT`、现有 `OrderCommitWatermark` 累计提交验证，接入 Common `StateMachineRecoveryCoordinator` 和 `OrderBusinessStateMachine`，业务恢复/增量回放/幂等收尾全部执行，但 readiness 保持关闭。封存完成后还故意覆盖原始 inbound 快照，确认不会用错误业务镜像。
- **Trade**：`TradeCommonRecoveryCoordinatorIntegrationTest` 使用 Common 真实封存文件及 `TradeBusinessStateMachine`，恢复余额、持仓、执行去重，再严格追平到已提交 HEAD，控制日志不反复应用业务，最终 readiness 仍关闭；另外验证 inbound 文件在封存后被替换不会篡改恢复结果。
- 上一轮 Order 和 Trade 的 **Spring 分区生命周期绑定**及真实本地 CQ 提交游标仍保留、默认 `commonBinding.enabled=false`。本次只升级不可变恢复契约，不启动真实副本自动晋升。

## 验收 / 版本

- Common 源码 `saas-crypto` commit **`5447d0d`**：Maven **149/149 PASS**。
- Trade 验证分支 `ha-common-state-machine-validation-20261011` commit **`b784f64`**：本地 Maven **247/247 PASS**，包含封存文件端到端测试。
- Order 验证分支最新 commit **`b6317de`**：新增 `OrderCommonRecoveryCoordinatorIntegrationTest`；专项 **9/9 PASS**，最新完整 Maven **335 tests, 0 failures, 0 errors, 1 skipped**，源代码提交已推送 GitHub 的验证分支。
- Mac 一致镜像基于 `Common 5447d0d` + `com.app.dc 2fa8047` + `Order 714441e` + `Trade 4244b79` + `MD bcdec88` 成功从源码编译 Linux/ARM64 开发镜像，Common JAR SHA-256 **`fb579b2b14fc1b4eab7327796c1505d61c01723549a4c6c9b7b49f57041b863e`** 在三个镜像一致；Common GAV `3.0.17-dev5447d0db20261011041324-SNAPSHOT`。构建根目录 `~/.opentradingcore/local-ha-sealed-final-20261011`；Order `b6317de` 与 Trade `b784f64` 比镜像组多的是端到端**测试代码**，生产业务源码没有再次修改；不能声称已发布 GHCR 正式版。

## 尚缺的生产闭环门禁（切勿称已上线）

**重要：封存文件的 durable seal 不是业务 Journal baseline。** `Control.persistVerifiedCheckpoint(request)` 的正式实现还必须在 service 分区排他恢复屏障里将**权威封存完整镜像 + 可恢复的 WAL baseline** 作为可审计事务持久化，并在崩溃重启后保证明确恢复点。当前测试中的该 baseline 和远端权威服务是 test double。不能仅凭 Common 149 tests 就将真实 Replica 变成 READY。

接下来：
1. Order/Trade 真实网络收取主节点权威快照、epoch+HEAD 证明和持久化后提交日志，禁止本地 Replica 未授权数据冒充权威来源。
2. 跨 ZK source assignment / old primary fencing / stage nonce 与 checkpoint id 的认证与二次复核。
3. 服务私有的 Journal baseline/rebase 安装、故障中断、crash restart、跨 epoch/幂等/无 GAP 验证。
4. 完整资金持仓、open order、Order→MD 水位及 Robot 后续对账完成之后，才开放 READY。
5. 原有两天 WAL 回收仍由 Common `SnapshotRetentionFence` 授权，必须有可信快照覆盖/消费水位/文件句柄退出，**不能仅按文件日期删除**。
6. MD 仍从 Order 当前权威全市场镜像 + 连续增量恢复，自动晋升的旧主 fencing/CAS 与全市场证明等门禁未通过；不启用 MD↔MD 日志，也不执行 SIGKILL。
7. Demo 正常环境保持现有 Primary；仅 Mac 本地隔离镜像验证，不发布 Maven Central，不替换线上容器，不触碰 10 租户数据。

本文件区分公共持久化封存**已完成**与跨服务 HA **未完成**。绝不以成功编译代替真实 failover 业务验收。
