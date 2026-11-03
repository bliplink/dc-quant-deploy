# T458｜Common / Order / Trade 自动恢复接线的安全候选（2026-11-03）

## 当前真实结论

**T458 源码门禁与分支候选已完成，正式 256 分区双向 HA 仍 NO-GO。** T456 只证明隔离单分区 Demo+Common 在旧候选 JAR 上的 A→B→A 与 E3 TCP fsync。不能把 T456 的证据迁移到下面新 Common 代码，也不能把源码编译成功误报为业务实测。

本轮没有重启或改动真实 Order/Trade、Gateway、Robot、MD、Projection；没有改动真实 ZooKeeper Manifest、P060 WAL 或证明链，没有使用 GitHub Actions。源码变更提交在**隔离开发分支**，未合入正式 `saas-crypto-latest`，防止在必需的物理证据生产者缺失时让现网 Spring 启动失败。

## 本轮实际完成的修改

### 1. Order / Trade 统一调用同一个 Common 自动恢复入口

隔离源码路径：
- Order: `.work/t444-order-stream/src/main/java/com/app/dc/service/state/OrderCommonNodeRuntimeWiring.java`
- Trade: `.work/t452-trade-windowed-e2/src/main/java/com/app/dc/service/state/TradeCommonNodeRuntimeWiring.java`

两服务仅更换启动接线，改用 `CommonCertifiedNodeBootstrap.openAndStartWithCertifiedAutomaticRecovery`，要求真实的分区级 `CommonCertifiedNodeRuntime.AutomaticReplicaRecoveryPlan` 与 `ReplicationControlHandler` 签名源配置。没有新增 Order/Trade 自己的 Epoch 选主、WAL、TCP 复制、Watch 或业务白名单；缺失这些依赖时抛出明确错误，不会装入客户可写 Registry。

**重要限制：** 目前源仓库尚无 `orderCommonAutomaticReplicaPlans`、`orderCommonSignedRecoverySources`、`tradeCommonAutomaticReplicaPlans`、`tradeCommonSignedRecoverySources` 的真实 Spring Bean 提供者。因此此改动是编译通过但**启动时必须拒绝**的候选，不是可以部署的新镜像。不能填空 Map 或总返回 true 的物理证明回调。

隔离开发分支（未合入正式）：
- Order：[codex/t458-certified-auto-bootstrap-candidate](https://github.com/bliplink/com.app.dc.ordersvr/tree/codex/t458-certified-auto-bootstrap-candidate)，HEAD `590be68c9135434f9c7f9683d297120bb9525fb4`；
- Trade：[codex/t458-certified-auto-bootstrap-candidate](https://github.com/bliplink/com.app.dc.tradesvr/tree/codex/t458-certified-auto-bootstrap-candidate)，HEAD `f934c0e5b68f1b1aa46b0a2d6b14fbd0b6e7bf07`。

### 2. Common 正式 256 分区 Home 原始拓扑门禁

在 Common 的既有 `CommonCertifiedNodeBootstrap.requireCompleteAutomaticRecoveryPreflight` 中，对 **256 分区**完整启动要求本地每个 Replica 恢复计划都有固定的 `originalHome`（完整原始 256 布局），防止“启动了 128 个 Replica 自动 Watch，但从未配置安全回 Home”的隐性错误。使用现有布局校验和复制的不可变布局，不新增角色、选主协议或恢复子系统。少于 256 分区的 Demo 与旧单分区验证保持原来的可选 Home 行为。

隔离分支：[codex/t458-256-home-failclosed-candidate](https://github.com/bliplink/com.app.common/tree/codex/t458-256-home-failclosed-candidate)，HEAD `57b8e94d4cc50d4c6cdf92c58f5d561802019a6a`，仅包含两个 Common 源码文件和一个原有 JUnit 文件的增量；三个文件的 Git Blob SHA 均已与本地工作树比对一致，未覆盖 T456 先前的其他代码。

## 本地实测

| 验证 | 结果 | 真实边界 |
|---|---|---|
| Order Spring Java 8 接线编译 | PASS | 使用现有 Surefire 依赖 classpath + T456 Common JAR，`javac -source 8 -target 8` |
| Trade Spring Java 8 接线编译 | PASS | 同上 |
| Order 缺失签名/计划依赖拒绝 | 3/3 PASS | JUnit 4；未启动 Spring/网络 |
| Trade 缺失签名/计划依赖拒绝 | 3/3 PASS | JUnit 4；未启动 Spring/网络 |
| Common 256 pinned Home preflight 编译 | PASS | Java 8，两个修改过的 Common 主类 |
| Common 自动恢复与 strict 相关回归 | **28/28 PASS** | Java 8 + JUnit 4，直接使用当前 Surefire classpath，与重新编译的两个 Main Class；涵盖 128 本地 Replica 无 Home 拒绝、128 完整原 Home 放行 |
| 新 Common 候选 JAR 打包、完整 Maven 回归 | **未完成** | 候选 JAR 创建操作被执行环境安全检查阻断，不能声称打包完成 |
| 新 Common 候选真实 Docker A→B→A | **未执行** | 缺新候选 JAR；T456 旧 JAR 通过不能代替新版本真实验收 |
| Order/Trade 256 真正自动切换 | **NO-GO** | 缺四个服务所需的真实恢复证明 Bean 与统一 JAR |

## 仍缺的真实依赖，下一步仅补这些，不再发明新集群

1. **在 Common 中复用既有 RSA / CommitIndex / Custody / ZK 物理验证**，为每个实际 Replica 提供真实 `LocalReplicaCatchupProof`、签名 `CertifiedRecoveryCompletion` 和 `RecoveredPhysicalPartition`；Order/Trade 只将各自现有的真实 Snapshot/Apply/WAL 重放适配进去。不能用空注册表冒充持久化证明。
2. **启用 Common 已有的真实控制 Source Handler**，源端必须读真实持久化 HEAD、签名旧 Epoch，并在角色失效后拒绝；不能使用静态伪 HEAD。全部 128 本地 Replica 计划必须含一致的 256 原始 Home。
3. **统一可构建的 Common Jar SHA**，完成各服务 Spring Bean 图及实际业务源端验证，在独立数据命名空间进行 256 分区真实 A/B 双向 SIGKILL、E3 READY、B 回归 WAL fsync、自动 Home 归还与资金/订单/成交/Projection 一致性。
4. **保留 P060 证据并修复认证根因**：Order P060 E2 `seq=188531` 的签名 fsync 回执失败导致 Epoch poison，A 多出的 1254 字节不具备有效提交证明，不允许旧 Epoch 直接续写或复制为客户已确认订单。ZK 上 256 READY 不是物理 READY。

明确结论：本轮是**源代码接线与安全前置校验进展**，不是完整生产 HA 验收；在缺真实计划和可复现 Docker 签名回归前严禁镜像替换。
