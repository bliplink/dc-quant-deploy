# T467｜Order/Trade 必须使用同一最新 Common：全量 Java 8 ABI、83 项业务单测、真实 JVM 类加载与现网 SHA 核查

**日期**：2026-11-03

**判定**：Order/Trade 构建和运行必须使用**相同 SHA-256 的统一 Common JAR**；当前这两个服务的最新本地源码与 T465 实测 Common 已做到编译和选定业务单测兼容，但完整生产自动 HA 仍 **NO-GO**。不能将本地源码/单测通过当作已经替换四个容器。

## 1. 唯一 Common 最新实测基线

- 仓库：`bliplink/com.app.common`，`saas-crypto-latest`，commit `5f04c8325fa1294eb28d7824093d05c6e09561ca`。
- 完整磁盘 JAR：`dc-quant-deploy/.work/t449-common-gw-rejoin/target/t465-common-real-physical-sources.jar`。
- **SHA-256**：`a0de1fb65d29e6ec6d2a9741c8b621c959c5bc3c63b1c7fcd5266c415fdc7c19`。
- T466 真实 3 ZooKeeper、双 JVM、256 分区 128:128 Home 压测共 **55,310** 次真实 STRICT 2/2 ACK；其中约 5 分钟持续负载 43,400 次全量原 WAL 校验均通过（详细见 T466 报告）。单分区 A→B→A 自动双 `SIGKILL` 回归通过，但 E2/E3 使用 LOCAL ACK，存在 RPO 风险。
- **T466 在 Common 生产库没有新增版本**，只是新增独立 Demo 压测源码与脚本，因此不要把 T466 的测试源码候选提交误认为新的 Common 运行时 JAR。

## 2. 四个正在运行的 Order/Trade Common JAR 不统一

从 Docker 容器内**直接读取**正在运行的真实 classpath JAR 文件 SHA-256（不是镜像名称或 Maven 版本号）：

| 容器 | 当前 Common SHA-256 | 是否等于最新基线 |
|---|---|---|
| `otc-t432-order-a-restored` | `5b3aa4055b5424980198705ee9dda6ab6b76de534636c368651540705e7611d0` | **否** |
| `otc-t453-order-b-standby-parent-watch` | `22b4b74213af025656cb9af47519a13325a6202bc39bc0f014d1e2ba5b4eb7b8` | **否** |
| `otc-t436-trade-a-margin` | `e7fe2fe519421632dac4080d6903ff23e6108f35ef13f4fb879efb994431ee72` | **否** |
| `otc-t452-trade-b-windowed` | `1c4765f603098bfed848b72144c7d6ebd9a6d7dfed59f3bac2db41ede6edef1a` | **否** |

四个运行镜像也分别为旧的 `local/otc-t427-order-a:wal-replay-256mb`、`local/otc-t453-ordersvr:standby-parent-watch`、`local/otc-t436-tradesvr:certified-margin-collateral`、`local/otc-t452-tradesvr:windowed-e2-rejoin`，**不能让它们承载最新 Common 的全 256 自动互切验收**。

## 3. 使用同一最新 JAR 完成整个源码编译及针对性业务测试

本地独立输出，不覆盖现网 Docker 镜像或生产 Common Maven 仓库：

| 验证项目 | Order | Trade |
|---|---:|---:|
| 本地 Java 8 编译服务完整 main 源码 | **120/120 PASS**（生成 177 个 class） | **170/170 PASS**（生成 217 个 class） |
| Spring 自动恢复/物理 HMAC 启动门禁精确 Common 3 类接线 Java8 编译 | **PASS** | **PASS** |
| 严格启动门禁及业务状态/恢复边界精选 JUnit | **19 PASS** | **20 PASS** |
| 撮合、撤单、部分成交、资金、杠杆和交易状态相关精选 JUnit | **20 PASS** | **24 PASS** |
| **实际 JVM ClassLoader CodeSource** | `CommonCertifiedSealedSourceData` 从**同一 T465 JAR**加载，SHA 与上方完全一致 | **相同** |
| **累计精选服务测试** | **39 PASS** | **44 PASS** |

总计 **290 个 main Java 文件编译通过，83 个精选 JUnit 测试通过**。编译路径先放唯一 T465 Common JAR，再放其余已有 transitive classpath；用真实 `Class.forName` 和 `ProtectionDomain.CodeSource` 反查 SHA，避免混进旧 Common。

本地实际证据：
- `.work/t444-order-stream/target/t467-latest-common-full-abi/`；`t467-latest-common-extended-junit.txt`、`t467-latest-common-business-junit.txt`
- `.work/t452-trade-windowed-e2/target/t467-latest-common-full-abi/`；`t467-latest-common-extended-junit.txt`、`t467-latest-common-business-junit.txt`
- Read-only 实时查证 JSON：`dc-quant-deploy/.work/t467-latest-common-check/readonly-physical-parity-and-providers.json`

**这里的测试是本机编译和精选业务单测，不是原版全 Maven 构建，也不是 256 分区正在运行的业务集群或 Docker E2E。**

## 4. 为什么还不能现在直接替换：六个真正缺失的 Bean

Order 和 Trade 源码中存在 `CommonCertifiedAutomaticSourceWiring` 和 `CommonCertifiedAutomaticReplicaPlanWiring` 的依赖装配，但下面六个被 `@Qualifier` 要求的 **真实 `@Bean` 提供者尚不存在**：

| 业务 | 缺失的实际持久化证据提供者 |
|---|---|
| Order | `orderCommonPersistedSignedSourceEvidence` |
| Order | `orderCommonPinnedOriginalHome` |
| Order | `orderCommonCertifiedPhysicalRecovery` |
| Trade | `tradeCommonPersistedSignedSourceEvidence` |
| Trade | `tradeCommonPinnedOriginalHome` |
| Trade | `tradeCommonCertifiedPhysicalRecovery` |

缺的不是配置字符串，而是验证旧物理源 CommitIndex/Custody、完整 256 原始 Home、原 Epoch 撤权/签名、从 Snapshot+WAL 追平、双 RSA READY 回执和当前业务状态安装的**真实独立持久化证据**。

T465 已提供的真实 Common 磁盘能力包括：
- `CommonPinnedRecoveryHmacKeyRing`：独立物理节点密钥文件，区分签名者和读取授权者；
- `CommonCertifiedPartitionRuntime.requireAuthenticatedOriginalSourceWal`：匹配真实双 RSA CommitIndex + 原始 fsync prefix 只读 WAL；
- `CommonCertifiedSealedSourceData`：SHA 封存 Snapshot + 已认证 WAL 的原始字节读取。

这些能作为真实 source adapter 基础，**不能通过空 Map/虚构 SourceHead/空 Home/无条件 READY 来补齐六个缺口**。现有 `OrderCommonRecoveredDomainWiring`、`TradeCommonRecoveredDomainWiring` 对业务状态的认证还仅覆盖原始 E1 Genesis，未完成真实 E2/E3 安装与业务回放。

## 5. 具体下一步（只修代码，不修旧数据）

1. 在 Common 中复用已通过测试的物理证据 API，为业务服务接通真正的源 Snapshot/WAL/CommitIndex、双 Custody 和原始 Home 验证；保持所有选主、状态机 WAL/Snapshot、TCP、追平和控制信令在 Common，业务仅提供 byte[] 业务快照/Apply。
2. 完成两个服务真正的六个证据 Bean 和 E2/E3 业务 Snapshot/WAL 安装；在隔离的新 256 分区 Demo 环境下实测自动 A→B→A 回 Home、故障期间业务写入及严格 2/2 恢复，不能将 LOCAL ACK 混称严格提交。
3. **然后**从统一最新 Common SHA 重建 Order-A/B、Trade-A/B 四个完全相同源码的本地镜像。每个镜像解包后检查 Common **只有一份**、四个 SHA 完全一致，再做 Spring 实际启动和签名 source/plan census 验证。
4. 若旧 P060 未认证尾部妨碍安装，按用户明确要求**不修旧 WAL**：清空 Demo 旧业务数据、全新命名空间/空卷重新注册租户、自动审批、Robot/Tape 报价点价、下单成交和资产/仓位/Projection 一致性，再压测和 A/B 双向故障注入。
5. 不使用 GitHub Actions。验收通过前原四个业务容器保持运行，禁止“只是换 JAR 就宣布 HA PASS”。

**T467 结论**：最新 Common 统一构建 **编译/精选单测 PASS**；真实生产部署与业务自动 HA **NO-GO**，这不是 Common 的 Java ABI 问题，而是明确的六个物理证据接线及 E2/E3 状态安装缺口。
