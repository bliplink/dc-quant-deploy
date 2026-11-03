# T462｜放弃旧 Demo 数据恢复，优先修 Common/Order/Trade 代码后全新部署（2026-11-03）

## 用户最新执行原则（必须执行）

> 如果工作内容是修复历史数据、旧分区、P060 未认证 WAL、旧 Snapshot 等，**停止修旧数据**；Demo 是可抛弃开发环境，可清空 Demo 业务数据并采用全新 ZK Namespace、全新 Genesis 重新注册租户。**如果是代码、集群机制、Order/Trade 接 Common、启动接线、业务 bug，就继续定位根因并修改源码、单测和实际部署验证**。

顺序必须是：**查明代码根因 → 代码修复和编译测试 → 完整镜像及真实 HA 依赖完成 → 全新 Demo 部署 → 新租户自动审批 → Robot/Tape 报价、点价 → 真实订单成交/余额/持仓/资金流水 → Order/Trade 256 分区自动 A/B 故障互切及一致性验收**。

- 不再将老 P060 的 1,254 字节未确认尾部修复、老数据追平、旧 Epoch/Custody 事务清理列为阻塞项。Old P060 仅作为历史证据，不能回写为交易。
- 不在代码和真实物理签名依赖缺失时直接清理**正在运行**的四个业务容器：T458 的 Order/Trade 自动启动候选仍缺少 Spring 实际的 `orderCommonSignedRecoverySources`、`orderCommonAutomaticReplicaPlans`、`tradeCommonSignedRecoverySources`、`tradeCommonAutomaticReplicaPlans` Bean。两个业务进程仍不具备 full 256-shard signed recovery READY 的完整接线；清空旧卷并不能弥补源码缺口。
- 新部署必须从全新、独立 Namespace + 空数据目录生成原始 E1 256 Home 128:128，不复用被 Poison 的旧 P060/旧 signed Stage/旧 Custody，确保镜像四节点同一 Common JAR SHA。旧运行容器仅在新的程序构建已准备好并允许安全切换后进行替换。不能从不完整的 Common Demo PASS 冒称业务全链路 PASS。
- GitHub 统一 `saas-crypto-latest`，本地构建测试，无 GitHub Actions。Common 全部统一机制，Order/Trade 仅业务 StateMachine/Snapshot/Replay，不得创建新选主或服务内复制机制。

## 本轮真实代码缺陷与修改（不是历史数据问题）

T460 原 Common 自动 Watch 带 `pinnedHome` 的路径存在生产逻辑漏洞：

1. `CommonCertifiedNodeBootstrap.requireCompleteAutomaticRecoveryPreflight` 要求每个 256 分区本地 Replica 的 `AutomaticReplicaRecoveryPlan` 都携带完整固定 Home 布局，正确。
2. 但 `CommonCertifiedFailoverWatch.probe` 之前采用 `if(pinnedHome!=null) coordinator.stageHomeReturn(...)`，**未区分**当前 Replica 是否为该分区原始 Home Primary。
3. 在 256 分区 128:128 Home 布局下，B 作为 P060 原 Home A 的备用节点也有 `pinnedHome`；一旦 A 的该分区 Poison（A 节点仍在线），B 便错误执行 `stageHomeReturn`，Common 严格拒绝 `candidate=B != homePrimary=A`，**阻断 B 的自动接管及 T460 RSA Poison 路径**。即使删除旧数据全新部署，同样会复现。
4. 现修复为 Common 内部依据原始、不可变 `PartitionBuddyPlacementPlanner.requireHomePrimary` **只选择路径，不授权 READY**：只有“当前 Replica 恰好是此分区原 Home”执行原有 `stageHomeReturn`；否则执行 `stageRecovering`（老节点 lease 真正消失时），或在受认证的同会话同 Manifest 旧主 RSA Poison 通知核验成功时执行 `stageSignedPoisonedPrimary`。
5. Home 归属判断在 Watch **构造时一次性**完成并钉住。无效/缺失 Home 布局会在构造时拒绝，而不是由后台 ScheduledExecutor 抛未捕获异常导致 Watch 无声死亡。没有新增线程、轮询和业务数据恢复代码；仍保留真实物理证明、旧主撤权、严格 ACK、E+1 业务 Replay/READY 认证。
6. 对原 Home Candidate 的独立 Replica WAL 追平验证继续执行；非 Home 待接管者仍由原 Watch 的 `requireIndependentE2ReplicaCaughtUp` 等门禁验证，配置完整 Home 不能禁用 Crash/Poison。

变更源码（全部 Common，不增加 Order/Trade HA）：
- `CommonCertifiedFailoverCoordinator.java`
- `CommonCertifiedFailoverWatch.java`
- `CommonCertifiedPoisonedPrimaryNoticeTest.java`
- `examples/common-only-demo/src/test/java/com/app/common/replication/CommonT460PoisonedPrimaryRealZkProcess.java`：增补真实三 ZK 256 Home B 非 Home 接管测试开关。
- 部署仓 `tests/run-t460-isolated-poison256.py`：`--pin-original-home`，强制真实三 ZK 以完整 Home 布局验证 non-Home 备用主切。

## 物理与自动验收证据

### 源码与候选二进制
- 从已通过 T461 的 Common JAR 增量替换 **两个 Common 正式类**；本轮并非全量 Maven clean package，正式部署仍必须从同一份源码统一构建并核对 SHA。
- T462 JAR：`dc-quant-deploy/.work/t449-common-gw-rejoin/target/t462-common-home-standby-takeover.jar`。
- SHA-256：**`54d58c53d490a6b14135c84f5bd426be158bed91b194d1a6fb7406e756ea153d`**。
- Common 两份正式 Java 源码+两份测试类本地/远程 Git Blob 哈希 **4/4 完全匹配**。

### 可复核测试

| 测试 | 实际结果 |
|---|---|
| 新旧 Common Java 8 源码/测试编译 | PASS |
| 包括新增 256 Home B 备用接管、无 Home 构造拒绝、真实 RSA 签名拒绝及 Common 自动 Watch 等 JUnit | **66/66 PASS** |
| 新 JAR，三 ZooKeeper + 独立 A/B JVM、真实不同 RSA、完整 256 Home；A 是 P060 原 Home，B 是 non-Home Replica，A 保持 lease LIVE 并发布真实签名 Poison | **B 以原 Common Watch 自动使单 P060 Epoch2 READY→Epoch3 RECOVERING；255 分区不变；无伪造 READY。PASS，退出码 0。** |
| 新 JAR，三 ZooKeeper + 128 Home Watch/原始 Home 反向 Stage 的完整控制面拒绝冒进 | **PASS，退出码 0**；缺物理 WAL 则不给 READY，不能称 256 分区业务恢复 |
| 新 JAR，独立 A/B/C Common Demo 的两次 `SIGKILL`、A→B→A、各自追平并进行真 TCP WAL fsync | **PASS，退出码 0**；LOCAL ACK 不能追溯为 Quorum |
| E3 A/B 两个独立磁盘实际 `cmp` 和 SHA-256 | **PASS**：两份均 178 字节，SHA `0935a4241ce2a5d1ab17137d29d2d8e5cec8c000e30346c69dbc0094a62ce689` |
| 真实 Order/Trade 256 分区 E3 双签名 READY、新租户 Robot Tape 交易 E2E | **尚未执行，NO-GO**，无法用 Demo 结果替代 |

证据目录：
- T462 256 Home non-Home signed Poison 三 ZK：`/Users/kong/dc-quant-deploy/.work/t460-live-poison-evidence/8b5364ea`，`candidate-b.log` 原文 `T462_REAL_3ZK_256_PINNED_HOME_NONHOME_B_POISON_STAGE_PASS partition=P060 oldEpoch=2 nextEpoch=3 unchanged=255 homePrimary=CommonHaDemoA candidate=CommonHaDemoB oldALease=LIVE signedOldA_RSA=true customerReady=false`。
- T462 256 分区 Home 控制面：`/Users/kong/dc-quant-deploy/.work/t462-real-256-home/target/t376-isolated-zk/t377-home-control-911ae94b.log`。
- 两次真 SIGKILL + B TCP fsync：`/Users/kong/.opentradingcore/t124-live-kill-runs/20261103203138`，附精确 `common-tested-pin.jar` SHA。
- 四个现有 Order/Trade 容器均仍 Up，原 P060 未改，测试容器已停止。

## 下一步代码优先项（无须再修老 WAL）

1. **先补真实 Spring 缺失 Bean**：统一使用 Common 物理签名 source handlers 和 128 Replica `AutomaticReplicaRecoveryPlan`，必须绑定真实 RSA、物理 WAL/Custody、Recovering Stage、Old-Epoch retirement、业务 Snapshot/Replay、E+1 READY 证据。任何空 Map、假 `catchup`、假 READY lambda 均不可用于生产 Spring。
2. 完整测试 `CommonCertifiedNodeBootstrap.openAndStartWithCertifiedAutomaticRecovery` 在全新 256 E1 两节点 Order/Trade 的真实启动与持续交易；把原 `E1` only business LoadedState 校验扩展为真正 E2/E3 恢复后在同一业务 JVM 的安装认证。
3. 使用全新 Demo 数据卷 + 全新 ZK namespace 从头部署，不搬迁或修补旧 P060，统一四个 Common JAR 同 SHA。新注册租户自动审批、Robot 点价/盘口、真实成交、资产持仓/订单/资金/Projection 一致性验收。
4. 再做 A 挂 B 接、A 恢复回 Home、B 挂 A 接、B 恢复回 Home 的真实业务 HA。**业务完整测试 GO 才允许宣布任务完成**。

最终结论：**T462 修复 Common 256 Home 备用接管代码漏洞 PASS；全新业务部署和 Order/Trade 真实 256 HA 仍 NO-GO。旧数据不再修复。**
