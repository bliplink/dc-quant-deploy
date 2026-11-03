# T464｜Common 统一 256 分区真实签名恢复源与 Replica 计划装配：已实现、已测试，正式 Order/Trade 仍待物理数据证据

日期：2026-11-03

## 结论

**T464 Common 源码与 Demo 隔离单测/故障回归 PASS；Order/Trade Spring 装配源码、Java8 编译及否决门禁 PASS；真实 Order/Trade 业务 HA 仍 NO-GO，未重部署。**

遵循用户最新原则：旧 P060、老 WAL 1254 字节未确认尾部、老租户状态等数据问题不再修。真实代码阻塞必须继续修；代码具备安全启动条件后用新 ZooKeeper namespace + 空卷重新部署，走自动审批、Robot、下单成交、Order/Trade A/B 自动切换及一致性测试。

## 1. 新发现的实代码接线缺口

T463 的 Order/Trade 自动启动候选已经要求 4 个 Spring Bean 名称：
- `orderCommonSignedRecoverySources`、`orderCommonAutomaticReplicaPlans`
- `tradeCommonSignedRecoverySources`、`tradeCommonAutomaticReplicaPlans`

但此前未提供 Bean 定义。更关键的是 Common 新自动模式此前只验证 Replica 计划是否齐全，却**没有同时验证启动前本地所有 256 分区的真实签名恢复源操作齐全**。传一个仅有 1 个分区的非空 Map，仍可能创建其他物理 WAL/Netty。不能等故障时才发现缺少 127 个 Primary 的 Snapshot/HEAD/Data；这是代码 bug，不是历史数据问题。

## 2. Common 通用代码完成

Common 新增两个业务无关的源/计划工厂，生产自动 HA 启动入口提前校验，**源材料只来自实际物理适配器**。以下类对 Demo、Order、Trade 完全一致：

- `CommonCertifiedAutomaticSourceWiring.java`：遍历当前已签名 ZK 分区 census，生成 Common 已有的四种 FINAL 物理签名处理器。对当前节点 Primary 必须有 `RecoverySourceHeadControlHandler`、`RecoverySourceManifestControlHandler`、`RecoverySourceDataControlHandler`、`RecoveryDurablePrefixControlHandler`；对本地 Replica 必须有独立 `RecoveryDurablePrefixControlHandler`。强制每个本地分区恰好对应角色所需 opcode，拒绝非 Common lambda、缺一分区、额外分区、空数据源与伪签名处理器。全量源 Map 不可变。
- `CommonCertifiedAutomaticReplicaPlanWiring.java`：从真实已签名当前分区 census、**另外持久认证的原始 Home**、原始两方 RSA、独立物理旧 Replica fsync、已签名 Stage coordinator、严格双方 READY 回执及业务 WAL/Snapshot 安装接口生成每个当前 Replica 的 `AutomaticReplicaRecoveryPlan`；任何缺项立刻拒绝。独立旧 Primary RSA 公钥逐分区绑定；生成后计划不可变。**固定 Home 仍是 128:128，但当前 Replica 可能因局部切换临时成为 129:127**，必须允许并保持原 Home 回切，不能硬写当前永远 128:128。
- `CommonCertifiedNodeBootstrap.openAndStartWithCertifiedAutomaticRecovery`：增加 `CommonCertifiedAutomaticSourceWiring.requireComplete(...)`，放在任何物理 WAL、Netty、Poison Notice 之前。原手动 E1 Replay 入口没有改动，也没有引入业务独立 WAL/HA。
- 新增 `CommonCertifiedAutomaticSourceWiringTest` 与 `CommonCertifiedAutomaticReplicaPlanWiringTest`。测试中的回调**全部在调用时拒绝给出物理签名/恢复 READY**；仅验证拓扑和装配，不冒充业务正向验收。

Common 全部 5 份新/修改源码与 GitHub Git Blob SHA 校验 **5/5 一致**，在 `bliplink/com.app.common` `saas-crypto-latest` commit **`70687a2886c074fe7490f31236c1f5c63a5e398b`**。

## 3. Order/Trade Spring 接线源码完成（保留候选，不合并不完整自动 HA 到正式交易分支）

- `OrderCommonAutomaticRecoveryDependenciesWiring.java`、`TradeCommonAutomaticRecoveryDependenciesWiring.java` 新增正式、具名的各 **2 个 Spring Bean**，名称与 T458 原启动 API 完全一致。
- Bean 只调用上述 Common 工厂，不做任何服务内主切、快照传输、HTTP、WAL/ACK。当前 ZooKeeper census 仍来自 Common `NodeClusterControlManager`，RSA 仍使用 `ExistingDemoRsaNodeIdentity`/统一节点 RSA alias。
- **关键限制**：此处的实际物理 Provider 尚不存在，不能使用测试回调/空证明代替。每个服务还必须提供 Common 类型的真实磁盘 `SourceEvidence`、真实 32 字节以上原节点 HMAC、独立授权 reader HMAC、**持久签名原始 Home census** 以及持久签名旧 Epoch/RSA 与 E(n+1) Snapshot/WAL 安装 `DurablePhysicalRecovery`。这些是独立真实证据适配器，不是 Spring 命名问题。它们缺席，Spring 必须失败而不能打开客户服务。
- T463 的两服务 `*.common.nodeRuntime.automaticRecovery=true` 默认严格模式保持；只有显式 `false` 才使用原 Common E1 Replay 引导，**没有自动 Watch，不算 HA**。
- 当前 Order/Trade 代码放独立候选分支，**未合入正式 `saas-crypto-latest`**：
  - Order `bliplink/com.app.dc.ordersvr` 分支 `codex/t464-order-physical-common-source-plan-spring`，HEAD `ea5aff8285c974daa5360db647d0c51271dd4ef8`。
  - Trade `bliplink/com.app.dc.tradesvr` 分支 `codex/t464-trade-physical-common-source-plan-spring`，HEAD `2917c8a2e6dd18dadd281d3b11031762cd0a5819`。
- 两服务各 2 个本轮变更文件，合计 Git Blob SHA **4/4** 本地/远端相同。

## 4. 本轮实测

| 项目 | 验收 |
|---|---|
| Common 5 份生产/测试 Java 源码 `javac -source 8 -target 8` | **PASS** |
| Common 完整 256 分区，A/B 主 128:128，持久化签名 source/Replica 128 计划、缺签名/伪 handler 拒绝、局部 E3 **129:127** 仍保持原 Home | **29/29 JUnit PASS**（结构/安全门禁，不是 E3 业务真实安装） |
| Order/Trade 各两项 Spring Bean Java8 编译，新工厂+默认自动 HA+旧 E1 手动引导门禁 | **Order 5/5、Trade 5/5 JUnit PASS** |
| T464 最终 Common JAR，独立真实三 ZooKeeper + A/B 两 JVM + 256 固定 Home，旧 A 不死亡、真实 RSA E2 Poison、B Watch 单 P060 E3 RECOVERING | **PASS**，255 其他分区 READY 不变；customerReady=false |
| 同一最终 JAR，独立 Demo A/B/C JVM，A→B→A 两次真实 SIGKILL、E2/E3 重启/追平及新 E3 Netty B 独立 fsync | **PASS，退出码 0**，严格记录 E2/E3 LOCAL ACK ≠ 正式 STRICT QUORUM |
| 最终 E3 A/B 原始 WAL 全字节比较 | **PASS**，A/B 各 178 字节，SHA-256 均 `0935a4241ce2a5d1ab17137d29d2d8e5cec8c000e30346c69dbc0094a62ce689` |
| 真实正式 Order/Trade 四个镜像 256 分区集群切换、资金持仓一致性、Robot/Tape 真实交易 E2E | **未执行，NO-GO** |

候选 Common JAR 路径：`dc-quant-deploy/.work/t449-common-gw-rejoin/target/t464-common-source-and-plan-wiring.jar`

SHA-256 **`053501729f7382e5cf5990add7e258d3c71be88e6e4bdc1010a5f388b7d0c445`**，使用原已验证 T463 JAR 加编译后 Common 3 个生产类；**不是 Maven full clean package，不是正式 Order/Trade 镜像**。

证据目录：
- 真实三 ZK 256 Home Poison：`/Users/kong/dc-quant-deploy/.work/t460-live-poison-evidence/4b09e5e8`。
- 两次真实 SIGKILL、独立 A/B/C RSA 和 E3 WAL：`/Users/kong/.opentradingcore/t124-live-kill-runs/20261103213015`，`common-tested-pin.jar` SHA 与 T464 固定候选完全一致。
- 旧四个 Demo Order/Trade 容器仍 Up，未替换、未修改旧 P060；隔离测试容器清理。

## 5. 下一步必须是真实物理适配器与全新部署

1. 在 Common 中实现实际物理源适配：从真实已有 RSA/签名 E1 Home、持久化 Snapshot/签名 Manifest、原始 WAL/CommitIndex、双 Custody、准确旧主撤权与新 Epoch 已安装业务 Image，给上述 `SourceEvidence` 和 `DurablePhysicalRecovery` 填充**可复核真实磁盘/签名来源**。Order/Trade 只能提供业务 byte[] Snapshot/Replay，不得自己实现选主/复制。
2. 统一本地全量构建 Common，四个 Order/Trade ARM64 镜像嵌入同一字节 SHA，实际进行 Spring 启动 + 256 分区 Netty/WAL 源处理器、128 Watch + E3 真签名 READY 验收。不得拿测试结构化装配或单分区 Demo 冒充完整 HA。
3. 之后用**全新 ZK namespace + 空卷**直接重装 Demo，不再修任何旧 P060 数据；新租户自动审批、Robot 自动报价/点价、真实交易撮合、余额/持仓/成交/Projection 一致性、A/B 双向自动切换和回 Home 达到 GO。

本轮 **Common 代码源/计划装配 PASS；业务证据适配器与正式业务自动 HA 仍 NO-GO**。
