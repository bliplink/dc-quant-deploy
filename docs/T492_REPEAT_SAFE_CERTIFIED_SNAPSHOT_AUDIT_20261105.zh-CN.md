# T492｜认证快照重复调度安全修复及 256 分区实测

日期：2026-11-05。**局部 PASS，生产 Order/Trade 完整自动 HA 仍 NO-GO。**

## 先定位到的实际缺陷

T491 接入了由 Common 统一调度的真实业务快照。如果当前 Primary 没有新的 WAL 提交，重复轮询仍会触发 Order/Trade `captureAtCertifiedWriterHead`，其中 `createdAt=System.currentTimeMillis()` 会使同一 `(epoch, seq)` 的快照内容 SHA 变化。Common 不允许同一物理 `epoch/seq` 重写不同 SHA；如果盲目持续重拍，会出现 `COMMON_SNAPSHOT_PIN_SAME_SEQ_CONFLICT`，甚至留下不同 SHA 的同序号不可变文件，影响后续 Catalog 唯一性验收。

**根因是调度器未判断已认证的不可变 Snapshot pin 是否仍覆盖当前提交水位，非 Order/Trade 序列化 bug。**

## T492 修复（完全留在 Common）

- `CommonCertifiedOpaqueSnapshotPin.existingWaterline` 只解析物理文件 pin 的 Epoch/Seq；该字段本身不授予 READY/ACK。
- `CommonCertifiedNodeRuntime` 每次调度先重新验证当前物理 2 RSA CommitIndex/Custody/WAL HEAD。若 pin 与提交水位完全一致，再由 `CommonCertifiedOpaqueSnapshotPin.reopen` 对**完整已封存 Snapshot**、物理 HEAD、不可变 pin 前后进行重新认证，只有成功才跳过重复序列化和 fsync。若 pin 比当前认证 HEAD 更新，则失败拒绝；真正有新提交才重新封存。
- 保留 `successful/rejected/unchanged` 可观测计数，拒绝不发布新客户 READY/ACK。Order/Trade 无需追加任何自己的集群代码。

## 可核验测试

1. `CommonCertifiedNodeRuntimeTest.freshCommonBootstrapBuildsAllPhysicalPartitionsFromVerifiedZkCensus`：独立 RSA A/B 真正严格提交后封存首张 Snapshot，等待下一轮**相同 HEAD**，assert `unchanged > 0`、`successful == 1`，物理目录 `.snapshot` 文件数**严格为 1**；Primary ZK 撤权后，成功数不增长，拒绝计数增长。`T492_COMMON_UNCHANGED_HEAD_PIN_REOPEN_NO_DUPLICATE_PASS`。
2. 使用干净的 SLF4J 1.7.30 测试类路径运行完整 Common 节点运行时 `15/15 JUnit PASS`，包括 T491 撤权门禁和 T492 重复调度；日志 `.work/t492-common-certified-repeat-snapshot/t492-full-node-regression-clean-slf4j.log`，无 `AbstractMethodError`。
3. 使用 **T492 候选 JAR 本身**、真实隔离 3 ZooKeeper、两独立 Common JVM、原始 A/B RSA，`256` 分区按 `128:128` Home，10/50/200 **模拟租户写入压测**每个节点 20+50+200 条严格持久化，共 540 条；全部客户端 ACK `failed=0`，逐分区两个物理 WAL 完全一致。日志 `.work/t492-common-certified-repeat-snapshot/t492-256-strict-load.log`，`T466_256_REAL_A_B_256_PARTITIONS_BITEXACT_PASS frames=540 partitions=256`。
4. 重新构建两份 ARM64 但未部署的候选镜像：`local/otc-t492-ordersvr:repeat-safe-snapshot-nogo`（ID `sha256:9fcdee79...`）与 `local/otc-t492-tradesvr:repeat-safe-snapshot-nogo`（ID `sha256:64ae9b4d...`），都装了**同一份 T492 Common JAR** SHA256 `fe028440679e118b4aacb48130033698cd1ef647de0131e86eb38b7918911ed8`，标签 `T492-NO-GO-physical-recovery-executor-missing`。

## 源码提交

`bliplink/com.app.common` 的 `saas-crypto-latest`：`CommonCertifiedOpaqueSnapshotPin.java`（`7342776`）、`CommonCertifiedNodeRuntime.java`（`a242d51`）、`CommonCertifiedNodeRuntimeTest.java`（`b520432`）。通过 GitHub 连接器按原文件 SHA 版本校验后分别提交，不使用 GitHub Actions。T491 的 Order/Trade 原业务 Snapshot Spring 接线已在各自同名分支提交，无需更改。

## 剩余生产 NO-GO

T489 的 `orderCommonCertifiedPhysicalRecovery`、`tradeCommonCertifiedPhysicalRecovery` 真实 Bean **均不存在**；`DurablePhysicalRecovery` 生产执行器还没有形成带原始签名 WAL、可认证 Replica、旧主隔离和双 RSA/独立见证 READY 的完整恢复链路。T492 验证了 Snapshot 生成、重复认证和原 WAL 严格提交，**没有**验证生产 Spring 真实 `Snapshot@S + WAL(S+1..HEAD)` 业务恢复、A→B→A 自动主切及同一租户真实 Robot/成交/资金/持仓/Projection。现有 Demo 容器保持原样，不允许以 Common 测试 PASS 擅自更新 NO-GO 镜像。