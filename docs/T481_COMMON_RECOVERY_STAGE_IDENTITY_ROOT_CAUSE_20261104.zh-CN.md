# T481｜Common 单入口安装暴露 Stage 恢复请求身份不稳定（2026-11-04）

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
