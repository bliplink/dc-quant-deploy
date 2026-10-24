# T72｜严格策略下无单副本客户 ACK 的自动恢复（2026-10-24）

## 结论

**真实 A → B 故障恢复到 Epoch3 严格 READY 已通过；B → A 反向自动晋升尚未通过。**

实验仅在隔离的 `otc-t71-strict` (3 ZooKeeper + 2 Java JVM + 不同 WAL 卷、同一 Mac) 上完成。选定的 `DEMO_V19_ACK_POLICY=STRICT_QUORUM` 保持不变，恢复期间拒绝单节点客户成功 ACK。没有切换成异步模式来回避完整严格认证。

## 本轮修复

1. **受认证的旧 Epoch 完整水位继承**。当 A Epoch1 写入 seq1 已得到两份真实独立的旧 Custody 认证后 SIGKILL A，B 在 Epoch2 `RECOVERING` 仍不得签发任何单副本客户 ACK。新增受限继承：只在 A/B 的原始 WAL SHA、业务 State、请求去重计数一致，且双方旧证书均明确认证整个当前 WAL 头、无未认证尾部时，允许旧 Epoch1 水位成为新 Epoch3 Genesis 的恢复候选。所有情况仍需旧授权过期、ZK 原子 FREEZE / PREPARE、真实新 Epoch 双 RSA 签名、双 Custody 持久化，以及最后的 READY CAS。**继承旧 WAL 头不是给客户确认任何新写入**。
2. **Learner 真实状态证明**。旧 A 回来时若 WAL 已与 B 完全一致，新逻辑将其作为已证明的旧头，而非不必要地要求必须先有 Epoch2 客户写入；继承分支重新核对 ZK 版本、两个物理收据与全部数据摘要，不再盲目替换 WAL。存在尾部不匹配时仍拒绝。
3. **避免同 JVM Custody 文件锁冲突**。第一次完成 Epoch3 READY 后，客户严格请求遇到 `OverlappingFileLockException`：因为本地严格签名路径和 Netty 服务路径创建了两份带缓存的 `DurableWalCertificateCustody` 实例。改为每个 JVM 共享唯一 `DemoV19Rf2DynamicReceiptService`，由 `DemoV19ClusterHarness` 注入严格 ACK 运行期；**不是移除文件锁、双 Custody 或 fsync**。

## 已完成的真实验收

- 清洁数据全流程：Epoch1 A/B 两份旧 WAL / RSA Custody seq1 → SIGKILL A → B Epoch2 RECOVERING（无客户单副本确认，严格 503） → A 恢复 → 历史水位双认证比对 → Epoch3 Genesis seq1 双签名/双 Custody → **自动 `V19_RF2_STRICT_READY_ACTIVATED epoch=3 seq=1`**。
- 使用共享单实例 Custody 修复之后，Epoch3 新请求获得 `QUORUM_DURABLE`、`quorumDurable=true`、`possibleDataLossIfPrimaryPermanentlyLost=false`，无伪造本地 ACK。
- 后续 30 条真实单笔 WAL、并发4：**30/30 及时 ACK**，吞吐 **2.958 WAL/秒**，单笔 P50 **1,429 ms**、P95 **1,783 ms**、P99 **1,970 ms**。这是单分区严格持久化指标，不是订单 TPS。
- 这一组结束时，A/B 都为 Epoch3 seq33，33 个独立 requestId，WAL SHA `aee36645df4297363b4d5333211472010f46f0094c7c03af1a69d428202c4cc3`、State SHA `790c4d64e4679394d52453a9ad7ca8333ddba214e0b64c18dde6da88b963af97` 完全一致。
- Java8 编译通过；`DemoV19Rf2StrictRejoinPreflightTest`、`DemoV19Rf2StrictCutoverPlanTest`、新增 `DemoV19Rf2LearnerCertifiedEpoch1Test` 共 **24/24 JUnit PASS**，覆盖缺少第二份认证、错误水位、未认证尾部、摘要不一致和正确继承。

## 仍未通过：反向自动主切

在 Epoch3 B Primary + A Replica 且30笔严格 ACK之后直接 **SIGKILL B**。A 未自动取代 B 发布新的 Epoch4/5 READY；真实客户写入返回 503（授权仍指向 B，未返回错误的本地成功 ACK）。B 恢复后，A/B 仍保持完全相同的最新 WAL 和 State，B 可再次接受严格 ACK，达到 Epoch3 seq34，WAL SHA `fd6686203a4251027ac65f2bf53ecc097d1dc2c9c50db1dd929f492c1a4955cc`，State SHA `dd228f9908f36e3fe0b9ceab69c51ae45ef3edb0c58d6f22fc74579d0dbaa4c8`。这**不是 A 自动接管成功**。

优先排查 `DemoV19Rf2AutoStage` 的自动晋升证据链仍调用固定 Epoch1 的 `DemoV19DurableRuntime.requireCertifiedOldRf2Survivor`，没有绑定最新 Epoch3 的权威 CommitIndex + 双 Custody 头及旧主撤权。下一关要让 N 次严格主切使用最新可信 epoch/current grant、累计 seq 和双独立 Custody；未达到新证据时必须继续拒绝交易，不能自行跳过。

## 环境和代码

本轮8个 `otc-t71-strict_` 证据卷保留；隔离容器全部停止，正式 Demo `dc-saas-*` 24容器保持原样。没有 GH Actions、GitHub 推送、正式 Common jar 发布、Order/Trade 接入。

T72 代码目前只在非 Git Pilot 源工程完成，通过完整源码归档保存；真正的 `com.app.common / saas-crypto` 公共 ACK API 是先前 T71 本地提交 `4058188`，**不要把本轮隔离 HA 修复冒充为已经发布到 Maven 或正式服务**。

源码和测试：`tests/patches/common-rf2-strict-inherited-head-t72-20261024.tar.gz`，逐文件校验 `tests/patches/common-rf2-strict-inherited-head-t72-20261024.sha256`。
