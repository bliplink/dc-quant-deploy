# T346–T347｜RECOVERING 分区从 READY Census 移除后的健康分区持续提交 + Common/Order/Trade 本地联编（2026-10-30）

## 本轮完成
- 改进 **Common 原有节点级运行时** `CommonCertifiedNodeRuntime` 的 `requireAuthenticatedReady()`、`requireAuthenticatedPartitionRole()`、`requirePrimaryRegistry()`。以前每次都要求当前已认证的 READY 分区数与启动时安装数完全相等；一个分区转入 RECOVERING 后，会误判整台节点没有完整分区，健康交易市场一并被拒绝。
- 现在 Common 仍核对最新签名节点级 ZooKeeper grant，**任何未安装的分区依旧拒绝**，对某个目标分区必须在该节点的 READY census 且角色与 Epoch 通过才能允许操作。节点级 writer registry 只是已有物理写入器的集合，不是新写授权；被移出 READY 的分区在每条 WAL 仍通过 per-shard grant 被拒绝。
- 扩充真实 Demo A/B RSA + 两分区 Netty 测试：P091 Replica 物理隔离后，模拟真实 ZooKeeper generation=2、P091 从 READY 消失；P091 Replica 请求被拒绝，Node A 的 P090 仍能成功第二次 `QUORUM_DURABLE` 原始物理 WAL 提交，独立 B Replica 水位精确追到 2。共享 Netty 没有停止。
- T346 Common 节点定向 13/13 PASS、0 skipped；**Common 全量 Maven 回归 153 suites / 655 tests / 0 failures / 0 errors / 63 skipped**。本地 Common commit **`265b13b`**（前置 T345 `2f684c7`）。
- 用同版本真实 Common Maven 坐标 `com.app.common:3.0.22-t143-durable-signed-crossjvm-handoff-20261026-SNAPSHOT` 在 Mac 做 `mvn -DskipTests install` 本地发布，随后对 Order/Trade `saas-crypto` 完整运行 Maven：**Order 44 suites / 137 tests / 0 failures / 0 errors / 2 skipped**，**Trade 52 suites / 207 tests / 0 failures / 0 errors / 0 skipped**。Order 两个需独立真实数据路径的测试在无参数全量套件中仍 skip；T343 先前独立真实路径运行 1/1 PASS，T344 尚未实物验证。

## 当前阻塞：E3 权限与自动切换
- 现场仍是 ZooKeeper `P193|2|OrderSvrB|OrderSvrA|STRICT_QUORUM|READY`，旧 B 节点租约存活、B 本地写入器已 poison；A 正式 Order 服务没有调用 Common 的 `armAutomaticFailoverWatch`。当前自动 watcher 仅在 B old-owner **临时 lease 退出**后签发下一 Epoch 的非路由 RECOVERING 阶段。
- 另一个 **Common 认证控制面接口不匹配**：`CertifiedNodeRecoveryGate` 目前要求 RECOVERING→READY 也必须增 Epoch。但标准严格主切先将 E2 READY CAS 为 **E3 RECOVERING**，完成独立双节点旧 Epoch 退休回执及两份 E3 签名恢复证明后，发布的是 **同 E3 READY**，不应再增 Epoch。绝不能简单移除拒绝分支：必须由 `CommonCertifiedStrictCrashReadyPublisher` 和原签名 Stage/物理恢复证据实现 READ-ONLY 验证，之后节点控制才能接受 E3 READY。现有 `CommonCertifiedStrictCrashReadyPublisher` 已验证 RSA 恢复回执后 CAS READY，但常驻 `CertifiedNodeRecoveryGate` 没有同 Epoch 恢复验证接线。
- Spring `OrderCommonPhysicalProofWiring` 创建原始物理证据 registry 但启动时为空；实际源必须由 Common 在真实 signed Stage 后安装。Trade 应走同 Common 实现，不新增业务专属集群。旧主 B 存活 lease 不能用伪造失联绕开。
- **未启动新容器、未重置 T330 原始金融 WAL、未造证书、未手工提升 READY、未用 GitHub Actions，也未证实线上 Robot/下单/成交/双节点互切**。

## 下一步必需
1. Common 统一实现并验证旧主 poison 自我撤权的真实 ZooKeeper 角色变迁（只冻结 P193，旧 B 节点其余健康分区继续服务），或在 B 原节点真实退出并释放 ZK lease 后由 A 常驻自动 Watch 发起 E3 signed Stage；切勿只靠业务层异常或脚本切换。
2. Common 把严格同 E3 RECOVERING→READY 的授权读取器接到已存在的 RSA old-physical retirement、完整 P193 原始 22667 CommitIndex/custody、E3 新主新备原始恢复快照和双签回执。新 READY 未核验前仍 NO-GO。
3. 把 Common 通用自动 Watch/恢复完成回调以纯 Spring 参数注入到正式 Order/Trade 启动（不能复刻集群代码），本地编译新镜像滚动部署、验证 Gateway ZK 重连、Robot 报价/点价成交、部分成交尾单/余额/持仓/Projection、连续 A↔B 故障自动互切。

**总状态仍 NO-GO，尚未恢复在线交易。**
