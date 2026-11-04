# T482｜Common 统一 Post-Open 认证 Source Factory，Order/Trade 删除重复集群接线（2026-11-04）

## 实测结论

**Common 统一物理 Source Factory 与 Order/Trade Spring 适配已完成、提交并回归 PASS；正式 Order/Trade 128/128 业务自动 E2/E3 接管、签名 READY、Robot 下单成交仍是 NO-GO。**

遵循用户要求：**Common 管所有选主、Epoch、Snapshot/WAL、复制、故障恢复和 READY；业务仅提供配置、业务 Snapshot/Apply。** 没有新增业务层 Watch、WAL、选主或 READY。

## 与 T481 根因修复的关系

T481 已修复 Stage 同一认证请求对象身份并重核 Snapshot/WAL/收据；Common 正式 `prepareCertifiedOpaqueBusinessBeforeReady` 在拒绝篡改 Stage 前先撤销旧回放准入。T481 使用同版 Common JAR 在隔离 Demo 实测 A→B→A 两次真实 SIGKILL、E3 B 重新加入并收到 A 新业务 TCP RSA fsync PASS；故障期 `LOCAL ACK` 且 `historicalLocalRpo=true`，不能宣称 RPO0。T481 源码已提交。

T482 解决另一处重复集成：原 `OrderCommonAutomaticRecoveryDependenciesWiring` 与 `TradeCommonAutomaticRecoveryDependenciesWiring` 各有 **44 行重复的**物理 WAL/CommitIndex/Custody/ZK 源证据循环构造，未来不可保证与 Demo 完全一致。

## T482 具体修改

1. Common `CommonCertifiedAutomaticSourceWiring.forCertifiedOpenedNode(...)` 新增统一**后置打开工厂**，接收 `service/node`、真实 `NodeClusterControlManager`、绝对磁盘 Snapshot root、已配置实际持久大小上限和原有物理 HMAC/reader provider。
2. **仅在 Common 实际打开各分区物理 WAL/CommitIndex/Custody 后、Netty Source Listener 绑定前**执行，针对认证 ZK census 的每个本地 Primary/Replica 核验分区、service/node、Epoch 和真实 role，严格检查 **本地完整分区数**，再调用已有 Common `fromOpenedCertifiedPhysical`、`bind`。每次 HEAD/Manifest/Data 请求仍用磁盘 sealed snapshot pin、真实物理 CommitIndex 与当前 ZK 证书，缺失拒绝。
3. Order/Trade 的两个 Spring `physicalSignedSources` 保留业务 `init`、已有 ZK、snapshotRoot、密钥配置和原有启动门禁，改为**同一行调用** Common `forCertifiedOpenedNode`；删除两份复制的源证据组装循环。
4. **不影响独立 `CertifiedPhysicalRecovery` 四项 Common 完整恢复要求**。它仍须提供旧 Epoch 的真实 RSA/Custody/CommitIndex / replica fsync / signed READY，不得以 SourceFactory 或 Test-only Stub 代替。

## 验证证据

候选 Common JAR（增量隔离，非 clean Maven production artifact）：
`.work/t449-common-gw-rejoin/target/t482-common-unified-postopen-source-candidate.jar`，SHA256 `305d4ba2b51c083e03af73984f5422c36eaeb4cf2fb5a1dbc5352c1a76e69916`；JAR CRC PASS、无重复 ZIP 条目，新的 Common API 已经用 `javap` 验证。

| 实际验收 | 结果 | 证据 |
|---|---|---|
| Common T482 Netty 实际双 voter Stage、Replay/ledger、v1/v2、ZK 和物理 WAL 回归 | **109/109 PASS** | `.work/t449-common-gw-rejoin/target/t482-common-unified-source-regression.log` |
| Order 包含新 Source Factory 不完整分区/错误服务/poison Primary 负面测试 | **52/52 PASS** | `.work/t444-order-stream/target/t482-full-main/t482-common-source-regression.log` |
| Trade 共用 Source Factory、恢复与资金持仓回归 | **64/64 PASS** | `.work/t452-trade-windowed-e2/target/t482-full-main/t482-common-source-regression.log` |
| Order 全部 Java 8 main | **122 source files / 179 classes PASS** | `.work/t444-order-stream/target/t482-full-main/javac.log` |
| Trade 全部 Java 8 main | **172 source files / 219 classes PASS** | `.work/t452-trade-windowed-e2/target/t482-full-main/javac.log` |
| Order/Trade 离线 ARM64 镜像与 Common class ABI 加载 | **两份 PASS** | 离线 `docker build --network=none`、`docker run --network none`，各只有 1 份 Common Jar |
| T482 同版两次 Demo SIGKILL | **本版未重新跑** | 不把 T481 的真实 SIGKILL PASS 冒充 T482 同版 |
| 正式业务 E2/E3 / Robot Tape 实际成交 / 256 分区双向业务故障 | **NO-GO，未通过** | 尚缺真实 Common `DurablePhysicalRecovery` 生产提供者及已安装业务快照血缘证据 |

候选镜像：
- `local/otc-t482-ordersvr:common-unified-source-no-go`，image SHA256 `d6364000c2353a6639f4eab7f2ab7189b09c48bba3f3302bd336b213bde0c723`
- `local/otc-t482-tradesvr:common-unified-source-no-go`，image SHA256 `1ee68d13e1a1b9dba93acb1edbd66eca9333dc9f94a74f0c38d6450aab53dea5`

都标记 `T482-NO-GO-until-signed-physical-recovery`；**四个业务容器、分区与现有数据未替换和未清除**。未使用 GitHub Actions。

## 已推送 GitHub `saas-crypto-latest`

- Common Source Factory [1cf5c94](https://github.com/bliplink/com.app.common/commit/1cf5c94c47390e0541b7bbbccbc1bd490c00cd47)
- Order Spring 适配 [791aace](https://github.com/bliplink/com.app.dc.ordersvr/commit/791aace86661614f3f7414bbc309e164feb2d868)
- Trade Spring 适配 [494b412](https://github.com/bliplink/com.app.dc.tradesvr/commit/494b4125a3a0787fae46f743fbd496414eb60011)
- Order 真物理分区负面验收 [de68b72](https://github.com/bliplink/com.app.dc.ordersvr/commit/de68b72e465706e1a41a108e4780c4b2807155be)

## 下一处真正剩余的阻塞

Common `CommonCertifiedAutomaticReplicaPlanWiring.DurablePhysicalRecovery` 四项生产实现尚未形成实物证据：signed Coordinator、独立 fsync catchup、两节点签名 READY 完成、Snapshot+原始 WAL 业务状态安装。将 Demo 已使用的真实 Common old-Epoch 证据/见证/Watch 操作和可持久化 Snapshot lineage 用 **相同 Common 接口**接起来，再发布新镜像；不能在 Order/Trade 另造集群，也不能伪造一个只有非空对象的 Spring Bean。

