# T468｜Common 双 RSA 持久化原始 Home + Order/Trade 实际 Spring 接线

日期：2026-11-04。分支：Common `saas-crypto-latest` 已合入；Order/Trade 两服务仍只在**候选分支**，不影响当前运行的四个容器。

## 本次实际修复的根因

T467 证实 Order、Trade 各缺少三个必需的自动 HA 证据 Bean：`PersistedSignedSourceEvidence`、`PinnedOriginalHome`、`CertifiedPhysicalRecovery`。即使最新 T465 Common 已在真实 256 分区 E1 STRICT 2/2 模式成功压测 55,310 次，**当前 ZooKeeper E2/E3 主备关系不等于原始 Home**。如果 A/B 中有部分分区临时切给对方，使用当前 manifest 恢复原始 Home 会造成 A/B 归属被永久漂移、不能正确自动回切。

此处新增的是 *原始 Home 的必要持久化证据*，不是新选主算法。Common 仍然统一负责 HA、WAL/Snapshot、TCP 和身份认证；Order/Trade 只进行 Spring 注入。

## 1. Common 正式实现

文件：`src/main/java/com/app/common/replication/CommonCertifiedOriginalHomeLedger.java`

- **签发**：`issueOriginalE1VoterReceipt(...)` 的生产入参必须为真实 `CommonOriginalE1SignedMembersSource`。该已有 Common 源按原始 ZooKeeper 同 Session 逐分区重验实际 E1 物理 Genesis、零已提交 WAL、双节点独立的业务 Snapshot 安装 Ledger/Journals，再返回两名物理选民；**未通过这项 E1 认证就不能签发**。
- 对全部 P000–P255 严格要求只有两个不同且各持有独立 RSA 公钥的原始物理选民，原始 Epoch 1、各主分区 128，固定 128:128 的独立原始 Home。禁止两个逻辑节点共用同一 RSA 公钥。
- A/B 每个真正的原始 RSA JVM分别对**同一份 canonical 256 Home**签名，按文件 fsync 和目录 fsync 写入 `original-home.v1`、`NodeA.original-home.rsa`、`NodeB.original-home.rsa`。不生成/覆盖密钥，不覆盖冲突签名和旧 Home 数据，发生部分写入时保持拒绝而非自动伪造恢复。
- **重新读取**：`requireBothOriginalRsaReceipts(...)` 必须在磁盘重新验证两名不同 pinned RSA 的 SHA256withRSA 签名、服务名和原始 ZK namespace、全量 256、连续 Pxxx、固定 128:128。一个签名、修改文件、错误分区、错误 RSA、其他业务服务、其他 namespace 都**FAIL-CLOSED**。
- 本源仅用于校验自动 A/B 回 Home 的 **原始身份 / 放置关系**，不是新的 ACK、READY、选主、ZK CAS、E2/E3 签名恢复或现场业务状态恢复。其读取不依赖当前 E2/E3 manifest，因此局部故障不会改变原始 Home。

Common 正式 `bliplink/com.app.common` `saas-crypto-latest` HEAD：**`1baa2e6d2d2105297158a30b9fa2e0d9c6071f79`**。只新增上述生产类和 JUnit 文件，已有 Common 生产提交链未改写。没有使用 GitHub Actions。

## 2. Order/Trade Spring 正式 API 接线（候选，暂不合并）

Order 候选 `bliplink/com.app.dc.ordersvr` `codex/t468-order-original-home-rsa` HEAD `9a34d3896b2a4dc6061d999b2d6b32217e2cca2f`。

Trade 候选 `bliplink/com.app.dc.tradesvr` `codex/t468-trade-original-home-rsa` HEAD `f8f51e6e31acf6a3dfb3ce8d196b5a32eba2a197`。

各新增两份仅做依赖注入的 Spring 配置类：

- `OrderCommonPinnedOriginalHomeWiring.java` / `TradeCommonPinnedOriginalHomeWiring.java`：真正定义过去缺少的 `orderCommonPinnedOriginalHome` / `tradeCommonPinnedOriginalHome` Bean。严格模式下以 `*.common.nodeRuntime.originalHomeLedgerDir`、`*.common.nodeRuntime.freshE1.namespace`、签名 RSA 原始节点和 `*.common.control.nodeId` 读取两个原始持久化签名；未 provision 拒绝启动，不回退到当前 ZK 映射、不采用测试常量。
- `OrderCommonOriginalHomeIssuerWiring.java` / `TradeCommonOriginalHomeIssuerWiring.java`：只在显式 `*.common.nodeRuntime.provisionOriginalHome=true` 时注入已有真正的 `*CommonSignedPreviousMembers` 原始 E1 双节点验证者、现有真实 RSA 私钥，逐分区重验原物理 E1 后尝试签名。没有 E1 Source、没有原始 E1 的物理证书/Session，则拒绝操作；默认值为关闭，不能在 E2/E3 重新制造原始 Home。
- 原有严格 HA Common Startup、原始 E1/回放、业务字节流和既有 256 分区主备未加新服务端集群代码。

## 3. 实际构建与测试

| 验收项目 | 结果 |
|---|---|
| Common 新生产类 Java 8 编译 | PASS |
| Common 双真实 RSA 文件签名的 256 原始 Home、缺少另一签名、篡改、错 namespace/service、公钥相同、错误原始 128:128 | **6/6 JUnit PASS** |
| Common 连同 T465 真实 Netty 双 RSA Custody、物理 fsync/WAL、封存 Snapshot、T464 全 256 源/Replica 计划、E3 129:127 回 Home 等回归 | **40/40 JUnit PASS** |
| Order 最新 Common Spring `PinnedOriginalHome` / 真实 E1 发行者 Java8 编译及自动恢复/物理密钥门禁 | **8/8 JUnit PASS** |
| Trade 最新 Common Spring `PinnedOriginalHome` / 真实 E1 发行者 Java8 编译及自动恢复/物理密钥门禁 | **8/8 JUnit PASS** |
| 同一 **T468 候选 JAR** 真实三 ZooKeeper + 两物理 JVM + 256 分区 128:128 STRICT QUORUM 下单调写入 | **540/540 STRICT 2/2 ACK PASS**；A/B 原始 WAL 全部 256 分区逐字节一致、序号连续 |
| 全套实际业务源 E1 双 RSA 256 凭据发行，真实 E2/E3 回 Home、资金/订单/持仓安装及业务自动切换 | **未执行，NO-GO** |

**T468 Common 测试候选 JAR：**

`dc-quant-deploy/.work/t449-common-gw-rejoin/target/t468-common-certified-original-home.jar`

SHA-256：**`300d16610d78e228db38c6d31b2ae16cd90e6078ac6051753bf3ac365dd12c2a`**。

这是已测试的 T465 Jar 增量添加一个已 Java8 编译的正式 Common 生产类，压测脚本固定 `common-tested-pin.jar` 与其 SHA 完全相同；**不是完整 clean Maven package，也不是已经发布的四个 Order/Trade ARM64 镜像**。

真实 256 E1 严格写入复测的报告路径：
`/Users/kong/dc-quant-deploy/.work/t466-common-256-strict/20261103162531-54986/metrics.json`
（对新 Common 候选执行，脚本成功码 0，记录 `T466_256_REAL_A_B_256_PARTITIONS_BITEXACT_PASS frames=540 partitions=256`）。

安全说明：Common Home JUnit 的生产性 RSA 验签是真实物理私钥与磁盘文件，但 JUnit 中用于发起原始 E1 256 Home 的入参是测试里的确定性 SignedPreviousMembers；**尚没有在一个完成真实全 256 E1 Genesis 双物理业务恢复的运行集群中实际签发两张 Home RSA 证书**。公开的生产发行入口强制真正的 `CommonOriginalE1SignedMembersSource`，不能把此单测冒称完整业务首次签发或故障回切验收。

## 4. 仍需立即执行的代码任务

六个缺失证据 Bean 中，本轮**两个 PinnedOriginalHome 实现已就位**。剩余 **四个**：

- `orderCommonPersistedSignedSourceEvidence` 与 `tradeCommonPersistedSignedSourceEvidence`：要真正接到本地持久化 CommitIndex/双 Custody、Snapshot Manifest 与 WAL 数据；Common T465 已有实际只读磁盘基础，但还没对应服务生产 Provider。
- `orderCommonCertifiedPhysicalRecovery` 与 `tradeCommonCertifiedPhysicalRecovery`：必须与 Common 的原 Epoch 退休/撤权、独立 Replica 追平、E2/E3 Snapshot+WAL 安装、两个不同 RSA READY 回执和业务状态机完成状态绑定。不能使用空 lambda 或假认证绕过。
- 在全新独立三 ZK/256 集群真正完成所有原始 E1 凭据发行，两证书独立 fsync，加载各个 Home Bean，并在**负载中 A/B 自动互切+回 Home**（不依赖脚本主切），E+1 客户端重新取得严格 2/2 ACK，然后全量资金/持仓/成交/余额/订单/Projection 对账。若仅实现带 RPO 的 LOCAL ACK，绝对不可标为严格无丢单。
- 达标之后才将 Order/Trade 候选合入 `saas-crypto-latest`，**统一使用同一 Common SHA** 重新构建/替换四镜像，旧 P060 数据不修；遇旧数据阻塞就空卷重新注册租户、Robot/Tape 真实流程。
- T466 已完成 55,310 严格 2/2 压测，本轮新 Common 又经过 540 严格回归；上线门禁仍是 **256 自动 HA + 真业务状态/回 Home 通过**。

当前四个运行中的 Order/Trade 容器没有替换、没有重启、没有清理旧 P060。隔离 T468 压测容器已清理；GitHub Actions 未使用。

## 5. 本轮追加完成的真实全量源码兼容回归

在上述 Common **同一份** `300d16610d78e228db38c6d31b2ae16cd90e6078ac6051753bf3ac365dd12c2a` JAR 下，实际重新编译了两个服务**全部 main Java 源码**，不是只编译新 Spring 类：

- **Order：122/122 源码编译 PASS**，产生 179 个 class；将签名原始 Home 的最新 Spring 接线与 Order 撮合、撤单、部分成交、Recovery、业务状态测试组合，**41/41 JUnit PASS**。
- **Trade：172/172 源码编译 PASS**，产生 219 个 class；将签名原始 Home 的最新 Spring 接线与持仓、保证金、资金入账、成交对账、Recovery、业务状态测试组合，**46/46 JUnit PASS**。
- **合计 294 个 Java main 源码、87 项精选 JUnit PASS**。非 full Maven clean package；不是 Docker 上的 Order/Trade 真实 E2/E3 资金/委托恢复验收。

本地证据：
- `.work/t444-order-stream/target/t468-latest-common-full-abi/`、`target/t468-latest-common-business-junit.txt`。
- `.work/t452-trade-windowed-e2/target/t468-latest-common-full-abi/`、`target/t468-latest-common-business-junit.txt`。

E1 原始 Home 凭据应在**真实原始业务 E1 双节点 Genesis 完成、零 ACK 证明仍成立**、尚未开始正式提交、仍持有原始相同 ZK Session 时，按两个物理 JVM 分别显式 `provisionOriginalHome=true` 签发。发行阶段 `automaticRecovery=false` 防止在双签名尚不齐全时自动 Watch Bean 抢先启动；收集两张独立 RSA 持久凭据后，在两个节点都将发行参数恢复为 false，再切换到自动 HA。不能在 E2/E3 根据当前主备重新发行，也不能借此跳过缺失的其他四个物理证据 Bean。
