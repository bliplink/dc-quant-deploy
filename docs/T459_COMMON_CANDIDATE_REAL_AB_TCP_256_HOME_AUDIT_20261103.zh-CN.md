# T459｜Common 256 Home 门禁：新 JAR 真实双向切换与三 ZK 256 分区回归（2026-11-03）

## 状态

**T459 Common 候选 JAR：单分区 A→B→A 真实 SIGKILL、RSA 恢复、B E3 TCP WAL fsync PASS。三 ZooKeeper 256 分区 Home 控制面/128 Watch 拒绝冒进 PASS。正式 Order/Trade 256 分区业务 HA 仍 NO-GO。**

本轮真实操作均使用独立隔离 Common Demo JVM / 数据目录 / 独立 ZK 控制面，未重启或替换现网 Order/Trade、Gateway、MD、Robot、Projection，也未写入现网 P060 的 Epoch、未确认 WAL 或客户数据库。没有 GitHub Actions。

## 新 Common JAR：可复核物理二进制

- 原 T456 Common 基准 SHA-256：`0e9205761029f2f616f65b42359606b0cdea79cc634bb8e10a147632c6b7f024`。
- T459 单独生成的 Common 候选 `dc-quant-deploy/.work/t449-common-gw-rejoin/target/t459-common-256-home-guard.jar`，SHA-256 **`80ec3deba2b38a3002f3d31d107f87ad1e8f094d8b9d2d315e7fbf15905616fd`**。
- 候选内容：在 T456 JAR 中更新从统一 Common 源码 Java 8 编译的 `CommonCertifiedNodeBootstrap`、`CommonCertifiedNodeRuntime` 和对应匿名/内部 Class；没有更改 Demo 业务镜像或线上服务。候选 JAR 的 ZIP 结构通过检查，`javap` 确认新增 `AutomaticReplicaRecoveryPlan.hasPinnedOriginalHome()` 方法。T456 原 JAR 保持 SHA 不变。
- 此构建是以已发布 T456 编译目标增量叠加特定 Common Class，并非全部 Maven Clean Package；已经通过 Java 8 重新编译和有针对性的物理回归。正式部署仍须执行完整、可重复的同源构建与四业务容器 SHA 校验。

## 源码修改与正式分支

Common 仅增加一个**启动前 fail-closed 门禁**：若服务有完整 256 分区，必须对每个本地 Replica 提供拥有原始 256 Home 信息的 `AutomaticReplicaRecoveryPlan`；否则拒绝启动。现有 Common Watch、ZK CAS、RSA、WAL、Custody、Epoch、READY 代码没有引入新业务语义，单分区 Demo 不强制 256 Home。

源码已从候选分支的三个文件按 Git Blob 校验合并到 `bliplink/com.app.common` 的 `saas-crypto-latest`：
- `CommonCertifiedNodeRuntime.java`：`24da18c087f93b150549da69d39fd7ad9d942e9e`；
- `CommonCertifiedNodeBootstrap.java`：`635b77f97c500e0418563b6ad65fd1c886f782b3`；
- `CommonAutoRecoveryPlanCoverageTest.java`：**`8ac1ee543e999ac98492dee96286ccda31dd863e`**。

Order/Trade 的 T458 Spring 启动接线继续保留在 `codex/t458-certified-auto-bootstrap-candidate` 分支，**不进入各自 `saas-crypto-latest` 和线上镜像**，因为真正的每分区 signed source、catchup、READY publisher、replay install Bean 尚未实现。不能用空 Map 或假签名认证占位。

## 实际测试结果

### A. Common Java 8 类编译与 JUnit

- 使用现有 Surefire 依赖 classpath 和本地 `javac -source 8 -target 8`，新源码 Main Class 编译 PASS。
- 用**新候选 JAR 优先于旧 target/classes 的 classpath**执行 `CommonAutoRecoveryPlanCoverageTest`、`CommonCertifiedNodeRuntimeTest`、`CommonCertifiedStrictCrashReadyCompletionTest`，结果 **28/28 通过、进程退出 0**。其中新测试验证：256 分区、128 本地 Replica 缺原始 Home => 拒绝；为全部 128 补上完整 Home => preflight 通过（不是签名 READY 证明）。

### B. 真实 A→B→A SIGKILL 与在线 TCP fsync（T459 候选 JAR）

原封不动使用既有 T456 真实脚本 `examples/common-only-demo/scripts/verify-real-auto-sigkill-genesis-replay.sh`，用 `OTC_T124_COMMON_JAR` 绑定新候选。所有 A、B、C 为不同 Docker JVM，C 仅持自己的独立 RSA 测试私钥。证据：

`/Users/kong/.opentradingcore/t124-live-kill-runs/20261103152042`

此运行的不可变 `common-tested-pin.jar` SHA-256 再次核验等于 `80ec3deba2b38a3002f3d31d107f87ad1e8f094d8b9d2d315e7fbf15905616fd`，脚本**退出码 0**。关键真实日志：

- `T124_REAL_E1_BUSINESS_UNDER_A_B_RSA_QUORUM_ACK=PASS`。
- `T124_REAL_SIGKILL_OLD_A_FULL_COMMON_DEMO_JVM=PASS`，`T124_COMMON_AUTOMATIC_SIGKILL_TO_DURABLE_REPLAY_COMPLETE_PASS epoch=2 seq=2 total=40`。
- `T130_CONTINUOUS_C_INDEPENDENT_E2_WITNESS_ISSUED_AUTONOMOUSLY=PASS`，B E2 本地续写 total=60，明确 `quorum=false rpoRisk=true`。
- `T126_REAL_A_RETURNED_REJOINED_B_E2_RSA_PREFIX_PASS seq=2 total=60 independentAReplicaFsync=true`。
- `T127_REAL_SIGKILL_E2_PRIMARY_B=PASS`，`T128_REAL_B_KILLED_A_COMMON_E3_FORMAL_REPLAY_COMPLETE_PASS committedGlobalSeq=4 restoredTotal=60`。
- `T130_CONTINUOUS_C_INDEPENDENT_E3_WITNESS_ISSUED_AUTONOMOUSLY=PASS`；A E3 本地续写 total=74、requests=6，明确 `quorum=false rpoRisk=true`。
- `T270_REAL_B_E3_ONLINE_RSA_REPLICA_REJOIN_PASS total=74 requests=6`。
- `T272_A_E3_COMMON_TCP_SIGNED_B_FSYNC_PASS seq=3 total=85 localAckNotRetroactiveQuorum=true`。
- **来自 B 自身独立日志** `t456-returned-b.log`：`T272_B_E3_COMMON_TCP_NEW_WAL_FSYNCED_PASS seq=3 total=85 requests=7`。

现场 A/B 两个独立磁盘路径下 E3 P090 WAL **均为 178 字节**，物理全文件 `cmp` PASS，SHA-256 都为 `0935a4241ce2a5d1ab17137d29d2d8e5cec8c000e30346c69dbc0094a62ce689`。没有将旧 LOCAL 客户 ACK 追溯升级为 Quorum。

### C. 真实独立三 ZooKeeper + 256 分区 Home

额外将同一个新候选 JAR 放入完全隔离的 `.work/t459-real-256-home` 测试目录，执行 `tests/run-t376-isolated-common-zk-stage.py --mode home256`，使用新建三个独立 ZooKeeper Docker 容器。证据：

`/Users/kong/dc-quant-deploy/.work/t459-real-256-home/target/t376-isolated-zk/t377-home-control-ffc448a7.log`

测试退出码 **0**、Docker 测试 ZK 全部停止。关键输出：

- `T378_REAL_3ZK_128_AUTO_HOME_WATCH_MISSING_WAL_DENIED_PASS totalPartitions=256 replicaWatches=128 unchanged=256 oldBLease=LIVE actualSharedControlThreads=2 autoEpochCas=0 customerReadyUnchanged=true`。
- `T377_REAL_3ZK_256_HOME_FIRST_RSA_STAGE_PASS total=256 unchanged=255 recovering=1 oldBLease=LIVE nextHomeStage=DENIED signedStage=FSYNC nonRoutable=true`。
- `T377_HOME_RSA_PREDECESSOR_NEW_A_SESSION_RESTORED=PASS total=256 recovering=1 oldBLease=LIVE otherShardsUnchanged=255 READY=false`。

**严格限定：** 第二组测试中 128 Watch 是缺真实签名 WAL 时的拒绝冒进负例。后续 P000 签名 Stage 是测试调用 Common 现有受认证接口，不是 128 分区全自动 READY。没有全部 256 实际 WAL / 128 Home 每个严格 READY / 全量性能与客户 ACK。

## 现网业务集群另一条已证实的根因

继续复查 P060 的根因链：
- Order A 的 E2 P060 在 `seq=188531` 收到 B TCP `127.0.0.1:45323 Connection refused`，已经落下 A 未认证的 1254 字节尾部后，`CertifiedBusinessCommandBoundary` 按设计 `fencePoisonedPrimary`。它是**分区级** poison，不是整个服务全 256 分区必须中止。
- `NodePartitionGrantTable.Permit.requireCurrent` 拒绝同 Epoch poisoned Primary，`NodeClusterControlManager` 仍可为其它健康分区续租节点。
- 当前真实 ZooKeeper `P060|2|OrderSvrA|OrderSvrB|STRICT_QUORUM|READY`，A/B 进程都还运行。Common 的普通崩溃 Watch 需要**旧节点租约消失**才能 `stageRecovering`；旧节点继续服务其他分区时，单纯 Poison 并不会让旧节点 EPHEMERAL Lease 消失。另一路 Common `stageCooperativeRecovering` 能处理旧主仍在线的严格复制协作切换，但需要独立真实旧主撤权/旧 WAL 退休及签名恢复证据；目前没有为 P060 自动触发并完成这条链路。
- 因而**即使替换所有四个 JAR 并启动普通 SIGKILL Watch，也不足以自动解决“节点还活着、只有一分区 Poison”的场景**。这是 P1 需要在 Common 里复用现有协作签名交接能力补齐的真实缺口；不能通过强行把 ZK READY 或未认证尾部当成成功来掩盖。

## 下阶段 GO 门槛

1. Common 在拥有有效旧节点租约但本地分区已 Poison 的情况下，利用现有受认证的协作 Stage/旧主逐分区撤权/双物理 WAL 证明启动**仅该分区**的高 Epoch 恢复；其他 255 分区不中断；不得把新业务私有 Watch/选主放进 Order/Trade。
2. Order/Trade 提供真实 128/256 Replica 分区计划、受签名 source handler、跨 E2/E3 不透明业务 Snapshot/Apply；四节点 Common Jar 的 SHA 必须完全一致；现场 E2 未确认尾部只作为证据封存。
3. 在独立全新数据和三 ZK 下完成全量 256 分区 A/B 主切、重加入、Home 自动安全归还和持久化/业务对账，再发布对应 Order/Trade 镜像。
4. 新租户自动审批、Robot 流动性/Tape、真实成交、余额/持仓/流水、MD QuerySymbol/APS、Projection 全链路一致才是最终业务 GO。

**结论：Common T459 单分区双向 HA 新 JAR PASS、256 物理 ZooKeeper 控制面负例 PASS、生产 P1 NO-GO。**
