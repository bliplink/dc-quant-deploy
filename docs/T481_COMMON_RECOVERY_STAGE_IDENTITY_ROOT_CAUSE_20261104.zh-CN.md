# T481｜Common 单入口安装暴露 Stage 恢复请求身份不稳定（2026-11-04）

## 修复验收结果（后续更新，覆盖下方历史 RED 状态）

**T481 请求身份问题已修复、正式提交；同版 Common/Order/Trade 本地回归 PASS。正式 Order/Trade 物理 E2/E3 自动 HA 仍 NO-GO。**

- **唯一身份**：`VerifiedRecoveryStagingClient.Result.verifiedInstallRequest()` 对同一 Stage 返回同一个 canonical `RecoveryRequest` 实例（Java8 `synchronized`）；但每次调用仍重新验证原始 Snapshot SHA/长度、原始 WAL SHA 及恢复收据完整内容，缓存不成为放行捷径。
- **恢复失败先隔离**：`CertifiedRecoverySourceAuthority.exactPinnedRequest()` 仅返回 Source Authority 固定的请求对象，不授予业务权限。Common 新 `prepareCertifiedOpaqueBusinessBeforeReady()` 直接进入现有 `CommonCertifiedRecoveryInstall.install()`，使旧业务回放准入**先撤销并将分区标记 NOT_READY，然后才复核 Stage 和独立物理 quorum**。即使 Stage 已篡改，旧恢复资格也无法残留。
- **三个业务共用路径**：Order/Trade 的 `*CommonRecoveryBinding.recoverCertifiedOpaquePhysical` 仅提供业务 `PartitionStateMachineRegistry`，统一调用 Common 的上述入口；不再提前读取 Stage，也没有本地选主、WAL、READY 逻辑。
- **实际负面测试**：同一 Stage 多次读取 `assertSame`；分别篡改收据、Snapshot、WAL 均拒绝，并在恢复原始字节后保持同一身份；真实双 Netty/HMAC voter Stage + business Restore/Apply/finish 各 1 次；已完成恢复后再次篡改 WAL 重试，旧 replay proof 立刻撤销，**没有二次 Apply，也没有 READY**。
- **隔离候选 JAR**：`.work/t449-common-gw-rejoin/target/t481-canonical-stage-before-ready-candidate.jar`，SHA256 `7bdecd2f1b455863434ed54e14f23c5d17b433d50ac97279f585354aa1629aea`。该 JAR 是按已通过编译的 class 增量封装、0 个重复 ZIP 条目，非 clean Maven 发布。
- **同版真实测试**：Common **109/109 PASS**（`target/t481-common-full-canonical-regression.log`）；Order **52/52 PASS**、122 源码 Java8 全量编译（`.work/t444-order-stream/target/t481-full-main/`）；Trade **64/64 PASS**、172 源码全量编译（`.work/t452-trade-windowed-e2/target/t481-full-main/`）；256 分区两 JVM/三 ZK 健康严格 RF2 **540/540 ACK 且 256/256 WAL bit-exact PASS**（`.work/t466-common-256-strict/20261104103423-15862/metrics.json`）。

**已提交 GitHub `saas-crypto-latest`：**
- Common canonical Stage [60ee176](https://github.com/bliplink/com.app.common/commit/60ee176929d46f5f50218779e5645f8673f57d65)、Source Authority [15f2da8](https://github.com/bliplink/com.app.common/commit/15f2da84820aa509c8a9fa50e1455c43c20528f4)、Common Pre-READY 入口 [4155b2a](https://github.com/bliplink/com.app.common/commit/4155b2ae520edd4fb9e0a7efdd5014c5655bd966)、Netty 篡改/恢复测试 [4b132f8](https://github.com/bliplink/com.app.common/commit/4b132f82f8e94034958090fc2b62255c8710d91a)
- Order 业务调用 [d1a4165](https://github.com/bliplink/com.app.dc.ordersvr/commit/d1a41658f39d5feca9e1ca33cefb138597e2c479)；Trade 业务调用 [3919732](https://github.com/bliplink/com.app.dc.tradesvr/commit/39197324007b14fde074e8b700d2f4f411f49825)

**同版 T481 Demo 真正双向故障实测补充：**隔离 Demo+Common 使用以上 **SHA256 为 `7bdecd2f...` 的确切 T481 JAR**，两次实际 SIGKILL A→B→A + A 追平 E1/E2、B 重新加入 E3、E3 新业务 TCP RSA fsync 至 B **PASS，脚本退出 0**。证据 `.work/t449-common-gw-rejoin/target/t481-two-sigkill-run.log` 和 `/Users/kong/.opentradingcore/t124-live-kill-runs/20261104183812`。故障期 `historicalLocalRpo=true`、`LOCAL ACK`，**不宣称 RPO0**。

**T481 ARM64 同版候选镜像**：`local/otc-t481-ordersvr:canonical-stage-fenced-replay-no-go`（`sha256:7f27d74bf926...`），`local/otc-t481-tradesvr:canonical-stage-fenced-replay-no-go`（`sha256:88fbf3537eee...`）。来自完整 Java 8 主源码输出，镜像中各只有一份 T481 Common JAR；在 `docker run --network none` 中 ABI/预 READY 入口类加载检查 PASS。**标签明确 NO-GO，未部署至四个现有业务容器。**

**仍未完成的门禁**：Spring 正式 `CertifiedPhysicalRecovery` 工厂、跨 E1/E2/E3 真实 RSA+Custody+WAL+Snapshot 证据、256 分区签名 READY、真实 Robot 成交、Order/Trade 双向 SIGKILL。现有业务容器未替换，也没有手工清除过期 lease 或 poisoned Epoch。下文是修复前的历史 RED 诊断，不代表最新状态。

---

## 状态与证据

**根因已通过实际双 Netty Stage 联合安装测试重现，修复未完成；禁止部署 T481 本地工作树和替换业务镜像。**

- T480 未改动的 Common 基线：**109/109 PASS**，日志 `.work/t449-common-gw-rejoin/target/t480-common-replay-gate-and-baseline.log`。
- T481 本地新增 `CommonCertifiedNodeBootstrap.prepareCertifiedOpaqueBusinessBeforeReady`，仅调用现有 `CommonCertifiedRecoveryInstall.install`，其最终签名 READY/业务 Writer 不在此方法授予。将 `VerifiedOpaqueV2NettyStagingTest` 的已认证 Stage/两节点 HMAC 测试接到此公共入口，实际测试 **RED（1 failure）**：`IllegalStateException: unexpected different recovery transaction`。堆栈 `CertifiedRecoverySourceAuthority.requireSource:76 → CommonCertifiedRecoveryInstall.installCertified:93 → CommonCertifiedNodeBootstrap.prepare...:52`，日志 `.work/t449-common-gw-rejoin/target/t481-two-phase-real-netty-install.log`。
- **明确根因**：`VerifiedRecoveryStagingClient.Result.verifiedInstallRequest()` 每次创建一个新的 `RecoveryRequest` 对象；而 `CertifiedRecoverySourceAuthority` 在创建时固定原始对象，`requireSource` / `requireFinal` 对请求执行 Java `requested != request` 精确身份检查。因此相同 Stage 多次获取的请求内容虽然一致，却不能重用旧 Authority，正式 Order/Trade 当前调用方式也可能重现。
- 安全修复要求：**在单个已持久封存的 `Result` 对象内缓存一个 canonical `RecoveryRequest` 对象，同时 `verifiedInstallRequest` 每一次调用都继续重新验证 VERIFIED_STAGING receipt、真实 image 文件及 SHA-256，不能因为缓存绕过认证，也不能放宽 Authority 的指针身份检查**。新网络 Stage 应产生新对象，禁止跨不同 Stage 共用身份。测试增加 `assertSame`、签名 source HEAD/两 voter 重查、Snapshot/WAL真实恢复和 tamper-after-cache fail-closed。
- 本地 WIP `VerifiedRecoveryStagingClient.java` 的缓存声明当前有一个 **Java 修饰符顺序编译错误**：`public StateMachineRecoveryCoordinator.RecoveryRequest synchronized verifiedInstallRequest()`；正确的语法应为 `public synchronized StateMachineRecoveryCoordinator.RecoveryRequest verifiedInstallRequest()`。尝试修正时平台执行安全检查拦截，**没有重试绕过**。此 WIP 不可发布，代码尚未提交 GitHub。
- T481 当前改动仅在 Mac 本地 `.work/t472-common-publish-20261104` 的脏工作树，包含其它历史未提交文件。**不能 git add -A 或把该工作树当做 clean 发布物。**
- 正在运行的 Order/Trade A/B 四个容器未改动，现有 T478 候选镜像未改动；无真实业务 E2/E3 双向故障切换或新租户成交成功证据。

## 确切下一步

1. 安全修复 Stage 的 canonical 请求身份并 **每次重新校验落盘 Snapshot/receipt**；先完成 Java 8 编译。
2. 同一个真实 Netty Stage 先创建 certified source Authority，再调用 Common 单入口，要求 Restore=1、Apply=1、finishReplay=1、`REPLAY_COMPLETE`，**READY=false**；篡改 Stage 重试不应二次 Apply。
3. 在 Order 和 Trade 只保留业务 `ReplicatedStateMachine` 回调并复用此入口，删除业务层重复的恢复协调；Common 对原始 WAL/双物理 voter/旧 Epoch/Custody 提供全部证据。
4. 补认证 E1→E2→E3 多 Epoch 非空业务恢复和真正两 RSA READY 后，才允许替换现有 Demo Order/Trade，运行 Robot/Tape 和实际双次 SIGKILL 对账。

**进度标准**：T481 仅证明了真实兼容性缺陷、仍为 NO-GO；旧 T478 HMAC Demo/Test PASS 不能宣称 Order/Trade 真实自动切换已恢复。
