# T348｜Common E(n+1) RECOVERING → 同 Epoch 严格 READY 的 RSA 物理证明（2026-10-30）

## Root Cause

- Common 的 E(n) READY -> E(n+1) RECOVERING 会在 staging CAS 中完成 Epoch 自增，后续两个恢复节点通过 RSA 收据/快照完成恢复后只能发布 **同一 E(n+1) READY**。
- `CertifiedNodeRecoveryGate` 旧代码把 `RECOVERING->READY` 的同 Epoch 一律拒绝：`RECOVERING to READY requires certified higher Epoch`。因此即使 `CommonCertifiedStrictCrashReadyPublisher` 有真双签证明并完成 ZK CAS，正式节点控制仍无法继续授权新 Epoch。不能单纯删除拒绝，否则没有恢复证明就可以伪 READY。
- T341 Common 分窗口读取器还有一项兼容问题：旧历史真实短 WAL 只给 65536B 预算，强制 `maxPayloadBytes>=1MiB` 会将原本可恢复的小日志拒绝。

## Fix in Common only

- 新增 `CommonCertifiedStrictStagedReadyEvidence`：仅在 **真实已 fsync 的原始签名 Stage**、ZK 版本和 exact E(n+1) manifest 一致时，且 **所有其他分区保持不变**，才接受新 READY 候选。
- 其 read-only 门禁同时验证：原始严格双节点 CommitIndex 和两个独立 RSA Custody 回执、A/B 原 WAL 的真实物理 HEAD 和 SHA（允许未认证尾部但绝不 commit）、两张 old-epoch 物理退休 RSA 回执、E(n+1) 双签密封新镜像、两张新 Epoch 物理恢复回执。完全复用 Common 的既有 Class，并未新建第二套集群/协议，不签发 ACK、不执行 ZK CAS。
- `CertifiedNodeRecoveryGate` 在同 Epoch RECOVERING→READY 时强制调用上述独立源；**未配置该源时依旧明确拒绝**。此前跨 Epoch 的严格恢复门禁原样保留。
- `ZkNodeScopedControlPlane.useCertifiedPhysicalEvidence` 提供可选新证据源重载；默认旧调用不改变行为，仍 fail-closed。
- `CommonFileBusinessWal` 将总体字节预算下界改为 `>=1`，每条数据仍有 MAX 上限、整个历史实际字节不能超过调用者预算和最高 64 MiB；旧短日志不会被强制当成 1MiB。

## Real evidence + tests

- 使用 Mac 原始 `/Users/kong/.opentradingcore/t293-live-rsa-20261029181500` 里的原 E4/E5 严格 A/B RSA、旧节点退休回执、E5 双节点恢复收据和密封镜像，新的同 Epoch READY read-only 控制验证器独立回归 PASS；测试也验证缺失验证器和错 staged ZK version 会拒绝。
- 原已有的 `CommonCertifiedStrictCrashReadyCompletionTest` 重新验证自动 Watch 严格 READY 与失去旧 A 退休回执仍然 NO-GO。
- 同时真实跑 P193 原始 RSA A/B、22667 条认证前缀、未认证第 22668 条隔离测试。
- **Common 全量 153 suites / 656 tests / 0 failures / 0 errors / 59 skipped，Maven exit 0**（指定 E4/E5 + P193 原始数据路径）；新增本地 Common commit **`3c43cd4`**。本轮将最新 Common JAR 本地安装至 Maven 缓存，同版本 Order 全量 44 suites / 137 / 0 failed / 2 skipped，Trade 全量 52 suites / 207 / 0 failed / 0 skipped。

## Still NO-GO

- 此补丁**只是 Common 读授权逻辑**；正式 Order/Trade 当前的 Spring 节点控制 `useCertifiedPhysicalEvidence(physical)` 仍不传新的严格 READY 源。Common auto Watch 也未被正式业务服务启动。
- 当前 P193 现场 ZK 仍是 E2 B Primary 及旧节点的正常临时 lease；新 E3 signed Stage、真实 old B/A 关闭收据、新 E3 完整业务状态安装、新 A/B RSA 恢复收据 **尚未产生**，不能重写或凭空签出。
- 原始 T330 Order WAL 仍 A=22667/B=22668（255/256 exact match，P193 extra tail），该尾部不能重复结算，也不能截断覆盖；Robot stopped。现网仍旧 T335/T336 镜像，并未完成交易功能验收或自动 A↔B。
- 下一步按原 Common 唯一 HA 规范实现 **真实 B 旧主隔离/撤权 + A 常驻自动 Watch + E3 signed Stage + 完整非空业务重放/双物理恢复回执 + READY**，然后本地重建和部署 Order/Trade，不绕过权限。

**最终验收仍 NO-GO；代码回归 PASS 不可代替 Mac Demo 真实交易。**
