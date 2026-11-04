# T478｜Common v2 网络认证恢复安装贯通与真实业务仍未 GO（2026-11-04）

## 结果
**Common v2 实际双节点 Netty 签名源 HEAD/Manifest、双物理 voter 原始 WAL quorum receipt、Snapshot+WAL 下载、业务 RESTORE/Apply、持久化恢复账本的统一调用：PASS（隔离集成测试）**。Order/Trade 真实生产自动 E2/E3 Replica 安装、两独立 RSA/ZK READY、Robot 下单成交与真实业务 SIGKILL：**NO-GO**。

### 直接复现根因 → 最小修复
T477 的 `VerifiedOpaqueV2NettyStagingTest` 已能 stage v2 Snapshot+单帧原始 WAL，但是把 stage 接到现有 `CommonCertifiedRecoveryInstall.install` 时抛：
`CertifiedRecoverySourceAuthority.requireCertified -> RecoveryQuorumWindowFromStaging.requireFullWindow: source full WAL window does not end at committed marker`。

根因：`RecoveryQuorumWindowFromStaging` 尚以 v1 `STATE_COMMIT` 控制尾标记生成全部窗口证据，未按 v2 取真实原始业务 WAL 最后一帧 SHA。新逻辑只在 `walProtocolVersion==2` 下强制所有物理记录为业务帧、最后一帧 seq 必须等于认证 HEAD、计算原始窗口摘要和 `RecoveryQuorumCommitAttestation.Prefix.opaque`，严格匹配认证 source HEAD；v1 原尾标记规则保留。

同时 `CommonCertifiedRecoveryInstall` 验证 fsync Ledger 的 protocol、Snapshot epoch/seq/SHA、Head epoch/seq、replaySeq，与真实请求逐字段一致才记录业务 replay；`CommonDurableBusinessReplayHandoff` 的全节点恢复期账本双读增加 `walProtocolVersion` 一致检查。

### 新增实际验收
`VerifiedOpaqueV2NettyStagingTest` 中启动两个真实 Netty Server，两个不同物理 HMAC voter Key（**测试签名，不是部署 RSA**）对相同源原始 WAL 做 independent quorum attest，先认证下载 Snapshot / 原始 WAL，再用 **已有** `CertifiedRecoverySourceAuthority` 新鲜 HEAD + 双 voter RPC 复检，调用正式 Common `CommonCertifiedRecoveryInstall.install` + `DurableRecoveryTransactionControl.forOpaqueCommittedWal`：
- RESTORE=1、Apply=1、finishReplay=1
- 认证 WAL 恢复到 seq=2，写入并回读 `DurableRecoveryInstallLedger.REPLAY_COMPLETE`（format=3/v2），校验当前 Epoch 的 in-memory ReplayGate
- **customerReady=false**，未授权 ZK READY，不尝试建立交易路由
- 篡改 staged WAL 必须在解码/回放前拒绝
- 原版先 RED（`source full WAL window does not end at committed marker`），修复后 GREEN。

测试源码 `bliplink/com.app.common/src/test/java/com/app/common/replication/VerifiedOpaqueV2NettyStagingTest.java`，本地结果 `.work/t449-common-gw-rejoin/target/t478-real-netty-v2-install-green.log`。

新增 `CommonDurableScopedBusinessHandoffTest`，验证持久 v2 Ledger 精确分区 P090 具备 independently verified proof 时才可准入；P091 未回放，global gate 仍拒绝；篡改协议与独立校验期间账本变化全部拒绝。3/3 PASS（proof callback 在单元测试中为 stub，**不提供外部签名成功证据**）。

### 同一最新候选
Common JAR `.work/t449-common-gw-rejoin/target/t478-common-v2-netty-durable-install-candidate.jar`，SHA-256 **223abacd4bd05757ce6f5241cdb8c71431f9d4991100a5a9c2fa1781923a889c**。增量测试候选而非 clean Maven 正式发布物。JAR 压缩/CRC PASS、0 duplicate zip entries。

| 测试 | 实测 | 证据 |
|---|---|---|
| Common 恢复/Netty/ZK/v1+v2/物理 WAL/控制/持久账本完整扩展回归 | **108/108 PASS** | `target/t478-common-full-netty-regression.log` |
| Order 与 T478 Common 同版 JUnit | **51/51 PASS** | `.work/t444-order-stream/target/t475-certified-snapshot/t478-latest-common-junit.log` |
| Trade 与 T478 Common 同版 JUnit | **63/63 PASS** | `.work/t452-trade-windowed-e2/target/t475-certified-snapshot/t478-latest-common-junit.log` |
| 2 JVM / 3 ZK / 256 分区健康严格复制 | **540/540 STRICT、256/256 原始 WAL bit-exact** | `.work/t466-common-256-strict/20261104092254-12360/metrics.json` |
| 正式 Order/Trade 真实 E2/E3 | **NO-GO** | 正式物理 recovery Bean / signed READY 未取得 |
| T478 最新镜像重建 | **未完成，构建命令被平台执行环境拦截** | T477 旧候选镜像仍在；T478 最新源/JAR 已编译单元测试 |
| 同版 T478 双真实 SIGKILL | **未执行，执行环境已有该项安全阻断** | 不用旧版 T476 答案冒充 |
| 正式新租户交易 | **部分 PASS** | 真实新租户 KJVLG7 TRIAL、自动审批/登录 PASS；Robot 自动创建 enabled=1，但 ERROR / 无挂单；Order 认证租约过期/poisoned Epoch |

### 生产阻塞与边界
当前业务四容器依旧 UP、未替换数据。旧配置 `durableHandoff.enabled=false`，新 `OrderCommonAutomaticRecoveryDependenciesWiring`、`TradeCommonAutomaticRecoveryDependenciesWiring` 仍需正式 `orderCommonCertifiedPhysicalRecovery`、`tradeCommonCertifiedPhysicalRecovery`。该 Bean 必须真实提供 Common 的 `DurablePhysicalRecovery` 四项：当前 signed Coordinator、旧 Epoch 双 RSA + CommitIndex + Custody / old owner revoked、独立 Replica fsync、Snapshot+完整原始 WAL 业务 restore+apply、双实体 READY。不得用 mock/fake READY。

还有真实跨 Epoch 历史 Snapshot lineage 的特殊情况：当前 v2 普通 Snapshot+认证 WAL 假设 source Snapshot 和 HEAD 属于同一 Epoch；E2/E3 多 Epoch 非空历史追平需要认证的 per-epoch prefix/继承水位，不可无证据放宽现有约束。**因此不能把本轮真实 Netty 单分区安装 PASS 解读成全部业务 128/256 分区跨 Epoch GO。**

下一阶段应该先完成真实 old-Epoch 物理签名授权与 Recovery Bean（纯 Common）、多 Epoch lineage 的真实证据连接并在隔离多 JVM 强测，再交付与部署正式 Order/Trade，测试注册租户→Robot报价Tape→入金委托成交→双次 SIGKILL 与一致性。
