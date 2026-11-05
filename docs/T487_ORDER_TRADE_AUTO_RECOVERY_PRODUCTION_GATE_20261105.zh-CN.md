# T487｜Order/Trade 正式自动恢复生产接线审计与 NO-GO（2026-11-05）

## 范围及事实

目标是 **同一份 Common** 负责真实 ZooKeeper 角色、原始 WAL/CommitIndex/Custody、签名、自动主备、Snapshot、恢复、READY；Order/Trade **只提供业务 byte[] 状态机**。不在订单或资金服务里实现第二套集群，不改变 Gateway 消息透传，不伪造旧 Epoch 身份、ACK、READY，不为了重新取得授权而删除 poisoned 证据。

截至本次审核，T486 与 saas-crypto-latest 的真实本地回归记录：

| 验收 | 真实证据 | 判定 |
|---|---|---|
| Common | `.work/t449-common-gw-rejoin/target/t486-common-full-regression.log` | **151/151 PASS** |
| Order | `.work/t444-order-stream/target/t486-allsource/order-full-regression.log` | **56/56 PASS** |
| Trade | `.work/t452-trade-windowed-e2/target/t486-allsource/trade-full-regression.log` | **71/71 PASS** |
| Common 同一候选 JAR SHA256 | `ac5d772e022bf82da63e5d51e6de3604ac32d274991bd25b00530a8dfe95b24e` | 校验通过 |
| Order/Trade 全量 Java8 编译 | Order 122 个源码文件，Trade 172 个源码文件 | PASS |
| 正式交易、自动 A→B→A、256 分区业务一致性 | 尚无完整生产级 E2/E3 物理恢复/交易证据 | **NO-GO** |

T485 之前的 Common 256 分区双 JVM 540 帧比对、10/50/200 模拟租户负载和 Demo 两次 SIGKILL 均有 PASS 证据，但不等同于正式 Order/Trade 的实测。Demo 中的故障期 LOCAL ACK **存在 RPO 风险**，不得写成严格双节点持久化承诺。

## 可定位的生产阻塞

### B1. Spring 缺少真正的 Common 物理恢复执行者（编译 PASS 不代表可以启动）

- `.work/t444-order-stream/src/main/java/com/app/dc/service/state/OrderCommonAutomaticRecoveryDependenciesWiring.java:98` 通过 `@Qualifier("orderCommonCertifiedPhysicalRecovery")` 注入 `CommonCertifiedAutomaticReplicaPlanWiring.DurablePhysicalRecovery`。
- `.work/t452-trade-windowed-e2/src/main/java/com/app/dc/service/state/TradeCommonAutomaticRecoveryDependenciesWiring.java:98` 对应 `tradeCommonCertifiedPhysicalRecovery`。
- 目前两份业务服务的 Java 源码均**找不到负责生产这两个命名 Bean 的实际 Provider**。
- Common 的接口不是四个空回调，四项必须真实提供：`signedCoordinator`、`independentFsyncedReplica`、`bothSignedPhysicalReady`、`recoveredBusinessWalAndSnapshot`。不能通过返回假的 callback 或禁用检查来绕过。

### B2. Common 原始旧 Epoch 物理证据注册仍未接通

- `OrderCommonPhysicalProofWiring` 和 `TradeCommonPhysicalProofWiring` 各自只创建一个初始**空**的 `CommonCertifiedPhysicalEvidenceRegistry`；空 Registry 的查询按设计拒绝。
- Common 已提供 `CommonCertifiedPhysicalEvidenceRegistry.installSignedSurvivor(...)`，但需要同一真实 ZK 的 RECOVERING Stage、独立签名 Stage Ledger、旧 Epoch A/B 固定 RSA、B 端原始 WAL + 双 Custody 收据、旧主隔离证明。
- 只有这些来自磁盘和真实 ZK 的材料全齐时，才允许 Common 为旧 Epoch 注册可信来源。仅存在旧数据目录、签名 Genesis 或 RSA 私钥都不能作为交易恢复证明。

### B3. 启动顺序存在真实依赖环

- `CommonCertifiedNodeBootstrap.openAndStartWithCertifiedAutomaticRecoveryFromPhysicalSources` 先调用 `attestedBusinessReplay.requireBusinessRecoveryReady`，随后才调用物理 `openAndStart`。
- RECOVERING 分区在原始 WAL/Snapshot 实际恢复之前不可能拥有新的完整 replay 证明。不能把这个检查直接删除：它阻止过早开启 Netty、授权写入以及错误发布 READY。
- 需要 Common 内部有界 **PREPARE（真实旧 Epoch 来源证明）→ INSTALL（隔离、原始 WAL/业务状态、持久化 ledger）→ ACTIVATE（重新校验签名/ZK 与业务，之后才允许 READY 和写）**。Order/Trade 共用同一路径。

### B4. 当前旧容器处于被拒授权状态，不能直接替换

2026-11-05 最新实际日志显示：

- `otc-t432-order-a-restored`：`java.io.IOException: node quorum lease expired`。
- `otc-t453-order-b-standby-parent-watch`：`Common poisoned primary Epoch cannot renew`、`ORDER_COMMON_CERTIFIED_BUSINESS_STARTUP_DENIED`。
- `otc-t436-trade-a-margin` 和 `otc-t452-trade-b-windowed`：容器仍是 running，但尚无在该环境的真实成交与余额一致性复验。

目前挂载的是 T398 私有持久数据卷，ZooKeeper 是既有真实三节点，不应重用旧的 poisoned Epoch。可根据用户约定在新的**隔离开发命名空间和数据卷**上干净部署，但必须生成真正的新一轮 E1 双 RSA 出生和控制面证据；不能仅重启或修改旧 ZK 节点的 READY 字段。

## 已落实与未落实的代码

- T485：修复 Order/Trade 有签名的旧 E1 Genesis 零状态 `committedStateEpoch` 元数据兼容；Order/Trade 原始 E1/E2 WAL 序号与逻辑序号分别验证；Trade 非空资金/100 倍持仓/成交去重与租户隔离 JUnit PASS。
- T486：`CommonCertifiedFullSnapshotReadback`、Order/Trade 独立回读核对：只在 **v2 非空、snapshotSeq == signed committed HEAD == replaySeq**、已 fsync seal 元数据和全 SHA 完全吻合时，回读实际业务状态；余额/订单簿发生变化即拒绝。**未**凭空跳过 Snapshot 后面的 WAL，**未**发布 READY。Common 151 / Order 56 / Trade 71 PASS。
- T485 ARM64 候选镜像已构建，标签明确 NO-GO。T486 统一 Common JAR 和 122/172 全量 Java8 编译、回归 PASS；本轮准备构建 T486 新候选镜像时，Docker 构建操作被执行环境安全检查拦截。因此**没有宣称 T486 镜像已构建、部署或取得交易恢复授权**；也未替换四个旧业务容器。

## 下一段执行顺序及实测门禁

1. **只修改 Common**：连接当前 ZK 严格签名 Stage 的真实物理证据 Provider；每次从持久化原始 WAL/两份 Custody/CommitIndex 校验；失证即拒，绝不复活旧主。
2. 打通 Common 的 PREPARE→INSTALL→ACTIVATE，至少一个真实 Order 分区和一个 Trade 分区带**非空业务状态**通过完整的 Stage→原始 Snapshot+WAL→新 JVM 回读→签名 READY；如还存在 WAL 后缀，必须真实回放并证明最终业务 Head。
3. Spring 只做**注入**：两个 `DurablePhysicalRecovery` Bean 绑定上一步真实 Common Provider；不能自行签 Epoch/CAS、复制、监听、授权 READY。完整 256 分区明确验证 A/B Home 各 128，不能因为某一分区 poisoned 撤销其他 255 个。
4. 在受支持的部署执行环境运行最新镜像的构建、容器类加载检查；旧 T398 不能恢复则建干净的新命名空间和原始双 RSA Genesis，不删除旧审计证据。
5. 正式注册租户→自动审批→Robot Maker/Tape 点价→买卖及成交→订单/资金/持仓/Projection 逐项一致；故障期间下单和新旧主旧 Epoch 隔离；真实 A→B→A、双方重启追平；10→50→200 租户压力、steady/burst/HA 注入。
6. 单节点故障仍继续写时明确采用经过证据约束的 `LOCAL_DURABLE_ASYNC`，单机 fsync 是恢复目标但**无双副本零 RPO 承诺**；两节点都健康时恢复严格副本 ACK，绝不虚构 2/2 证明。

**最终状态：源码级恢复与候选 JAR 的测试为 PASS，正式自动恢复 Spring 接线和业务部署为 NO-GO。**
