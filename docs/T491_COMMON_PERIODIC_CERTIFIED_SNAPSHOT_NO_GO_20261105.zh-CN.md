# T491｜Common 认证定时业务 Snapshot 接线与生产恢复门禁

日期：2026-11-05。结论：**T491 局部 PASS，Order/Trade 生产完整自动恢复及新租户真实成交 HA 仍 NO-GO**。

## 真实根因及边界

- `OrderSnapshotManager.sealCommonCertifiedOpaqueSnapshot`、`TradeBusinessSnapshotCapture.sealCommonCertifiedOpaqueSnapshot` 已负责真实内存业务的 `byte[]` 序列化；`CommonCertifiedPartitionRuntime.sealCurrentCertifiedOpaqueBusinessSnapshot` 已有严格两 RSA/CommitIndex/Custody/WAL HEAD 持久封存。但原生产代码没有任何调度入口调用该业务封存方法，因此按时间自动生成真实业务快照这一环未接通。
- T491 在**统一 Common** 的 `CommonCertifiedNodeRuntime.startCertifiedPeriodicBusinessSnapshots(...)` 接入一个全局有界定时工作线程及分区轮询。每次封存都验证现有 Common Primary ZK 角色；真正的 commit+apply 快照屏障、两 RSA HEAD、不可变封存仍完全属于 Common。失败只计拒绝，不发布 READY/ACK，不创建额外业务 WAL。
- Order/Trade 各新增 `OrderCommonPeriodicSnapshotWiring` / `TradeCommonPeriodicSnapshotWiring`，只注入原业务 Snapshot Manager/Capture，配置 `snapshotRoot`、`snapshotMaxBytes`、`snapshotSweepMs`。开发环境全新空数据目录允许自动创建，但仍禁止符号链接目录。
- 另外 T490 补充业务负测：签名快照 `seq=3`，伪装持久恢复 HEAD `seq=5`（但未真正重放 WAL 后缀），Order/Trade 均按 Common `COMMON_NONZERO_FULL_CHECKPOINT_EXACT_SIGNED_HEAD_REQUIRED` 拒绝。不把已经验证的 Snapshot 误认成 Snapshot+WAL 后缀回放证据。

## 验证证据

1. Common Java 8 编译、Order/Trade Spring 配置 Java 8 编译通过。
2. 使用现有 Demo 两独立 RSA、真实双节点严格 WAL/Custody、同 JVM Common 的 `CommonCertifiedNodeRuntimeTest` 测得 `T491_COMMON_PERIODIC_STRICT_SNAPSHOT_SEALED_AND_REVOKED_PASS`。真实封存成功，撤销 Primary ZK 授权后没有继续生成不可信 Snapshot；全组 `15/15 JUnit PASS`。日志 `.work/t491-common-certified-snapshots/t491-real-snapshot-test.log`。
3. 测试 classpath 原先混入老 SLF4J 实现，出现 `AbstractMethodError`（该轮 15 JUnit 仍成功但不能忽略日志）。重新以唯一 SLF4J 1.7.30 重跑物理快照用例，`run=1 failures=0 ignored=0`，没有 `AbstractMethodError`；日志 `.work/t491-common-certified-snapshots/t491-clean-snapshot-only.log`。
4. Order/Trade T490 快照签名读回及伪造 WAL 后缀拒绝各 `1/1 PASS`：`.work/t444-order-stream/target/t490-suffix-negative/run.log` 与 `.work/t452-trade-windowed-e2/target/t490-suffix-negative/run.log`。
5. 本地 ARM64 镜像 `local/otc-t491-ordersvr:common-snapshot-nogo`、`local/otc-t491-tradesvr:common-snapshot-nogo` 已构建。两镜像的**同一份候选 Common JAR SHA256**：`713785abebb8564c034396569f9fe3163ba16de043e6ed166707fb10706e5069`，标签均 `T491-NO-GO-physical-recovery-executor-missing`。

## 已发布源码（saas-crypto-latest）

- Common：`bliplink/com.app.common` 的 `CommonCertifiedNodeRuntime.java` 和 `CommonCertifiedNodeRuntimeTest.java`，通过 GitHub API 分别提交 `bd1d10a`、`e95e96f`。
- Order：`bliplink/com.app.dc.ordersvr` 的 `OrderCommonPeriodicSnapshotWiring.java`、`OrderCommonNonzeroSealedReadbackTest.java`，提交 `425a567`、`f748a4f`。
- Trade：`bliplink/com.app.dc.tradesvr` 的 `TradeCommonPeriodicSnapshotWiring.java`、`TradeCommonNonzeroSealedReadbackTest.java`，提交 `e5449d4`、`dd83612`。
- Mac 直接 `git push` GitHub HTTPS 曾因 443 超时；以上单文件通过 GitHub 连接器提交，并进行了原文件 SHA 核对。未触发 GitHub Actions。

## 下一阻断，不得降低标准

- `orderCommonCertifiedPhysicalRecovery` 和 `tradeCommonCertifiedPhysicalRecovery` **依然未有真实生产 Bean**。必须统一在 Common 接通旧主隔离、ZooKeeper 签名 Stage、完整持久 Replica fsync、双 RSA 原始 WAL+Snapshot 安装与签名 READY；Order/Trade 只注入同一 Common 执行器，业务仅提供状态机和快照数据。
- 完整新纪元 `Snapshot@S` + `WAL(S+1..HEAD)` 恢复并同 JVM 真实业务最终读取仍未被上述 T491 Snapshot 自证；必须基于认证 Common 安装器/原始 WAL，不能放宽 `CommonCertifiedFullSnapshotReadback` 门禁、不能伪造已完成标记。
- **未部署候选镜像、未清空 Demo、未进行本轮业务容器 SIGKILL、未完成新租户审批→Robot 报价/点价→成交/撤单→资金持仓 Projection→Order/Trade A→B→A 双向自动互切**。容器 UP、编译与 Common 测试不能算 GO。