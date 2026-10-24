# T73 — Common RF2 STRICT_QUORUM 反向与多轮真实自动主切（2026-10-24）

## 结论和边界

**隔离 Common 单分区 P000 的严格持久化 A→B→A→B 多轮自动主切及相应双副本恢复验收 PASS。** 同一台 Mac 内 3 个 ZooKeeper 容器、2 个独立 Java8 Netty JVM、各自 WAL 卷构成试点；这不代表生产多物理节点，也不代表 Order/Trade 账务业务集成、200真实租户压测或跨网络分区零双主已通过。

T72 已验证 A→B：Epoch1 旧受证 WAL seq1 → SIGKILL A → B Epoch2（客户 STRICT 被拒绝） → A恢复 → Epoch3 真实2/2 RSA WAL签名、独立双 Custody、真实 READY → 单笔与30/30严格ACK。
T73 在原 T72 **保留 WAL/ZK 数据卷**继续：

1. **B→A 反向自动主切**：Epoch3 B Primary / A Replica，均持久化到 seq34。SIGKILL B 后 A 用自己的旧 Epoch3 Custody 验证 seq34，ZooKeeper 自动原子进入 Epoch4 RECOVERING，随后状态可自动进入 `AUTO_DEGRADED_LOCAL_DURABLE READY`，但客户端已明确选定的 `STRICT_QUORUM` 不允许降级成功ACK，Netty返回明确503。这一步不需要人工脚本操作ZK或发布READY。恢复 B 后，自动校验旧主撤权和真实两物理 WAL，准备 Epoch5 Genesis seq34、RSA双签名、双Custody fsync和 READY，新的单笔严格请求返回 `QUORUM_DURABLE`（`quorumDurable=true`、`possibleDataLossIfPrimaryPermanentlyLost=false`）。
2. **Epoch5 业务等价写入**：30个真实Netty单笔WAL写入并发4，**30/30客户端及时严格ACK**，TPS **2.993**；单笔 P50 **1261ms**，P95 **1670ms**，P99 **1828ms**。结束时 A/B 同为 Epoch5 seq65、65 distinct requests；WAL SHA256=`b5e2501bfe164cf229d36741809dbb752e6fcf2759cc5b0b468bba51501fd7cd`，State SHA256=`25340c6f0a29a8b8200204d681e4338e4dec7c23e1529a2c2906ff3e9cb03d43`。
3. **第三次主切 A→B**：在 Epoch5 A Primary / B Replica 且 seq65 双物理 WAL一致时，SIGKILL A。B 最新旧 Epoch5 Cert/Custody 考证 seq65 后自动进入 Epoch6 RECOVERING、降级状态，但在严格策略下客户503不被误认ACK；恢复A后自动建立 Epoch7 最新 Genesis seq65、双RSA、双Custody持久化，发布 `V19_RF2_STRICT_READY_ACTIVATED epoch=7 seq=65`，B新的严格请求 seq66 成功。
4. **Epoch7 并发与最终一致性**：30/30 单笔严格ACK，并发4，TPS **3.085**，P50 **1256ms**，P95 **1620ms**，P99 **1765ms**。最终 A/B 均 Epoch7 seq96、96个不同请求、WAL SHA256=`d7269d3979d9d5c34dc78eb99a5c6127e7e730a15c0469e8a6a22b83a74f0f46`、State SHA256=`eedebd0b69694cee00c9b3d07551fc577a24e1286068b9330dabd10aeecd081e`。没有观察到重复应用或已确认 WAL 最终不一致。

## 根因与修复

- **主因**：原 `DemoV19Rf2StrictFailoverEvidence.verifiedHead` 即使在当前 JVM 的 Netty动态收据处理器已经持有唯一旧 Epoch Custody 文件锁时，仍新建第二份 `DurableWalCertificateCustody`，导致 `OverlappingFileLockException`，让 `DemoV19Rf2AutoStage.tryStageDegradedFromStrictReady()` 反复无法取得旧 Epoch3 最新真实签名证明。
- **修复**：`DemoV19Rf2DynamicReceiptService.verifiedCachedHead` 通过当前 pinned membership digest + 当前内存缓存实例读取原已经验证的物理证书，绝不重开已有锁；`DemoV19Rf2StrictFailoverEvidence` 注入同一 signer，验证旧 Epoch、配置版本、实际签名水位和本地 fsynced WAL 全部一致且不存在未认证 WAL 尾部。ZK CAS 之后的 staged recovery 只能复用本次 CAS 之前真实认证的旧物理头（epoch、config、primary、seq、SHA全匹配）并再次核验本地持久化 WAL；进程重启且无缓存时再在无人持锁条件下由旧持久文件校验原签名，不以缓存承诺代替物理証据。恢复和发布仍经 ZK 多数派、Epoch CAS、Lease 和下一任双 Custody。
- `DemoV19Rf2AutoStage` 和 `DemoV19ClusterHarness` 给故障核验器注入这份共享 signer；不移除文件锁、不绕过 fsync/双签名/证书；旧静态 Epoch1 回调仍存在，需要后续统一迁移到最新连续 CommitIndex + Custody 证据。

## 单元测试与限制

Java8 源码编译 PASS。JUnit包含原 `DemoV19Rf2StrictRejoinPreflightTest`、`DemoV19Rf2StrictCutoverPlanTest`、`DemoV19Rf2LearnerCertifiedEpoch1Test` 和新 `DemoV19Rf2StrictFailoverEvidenceTest`，共 **25/25 PASS**。新测试防止旧缓存证书被不同 Epoch、配置版本、Primary、seq 或 SHA 复用。

此次 200 模拟客户端严格压力未能重测（一项测试执行被执行环境检查阻止），不能写成通过。此前 T68/T70 明确显示严格逐笔 TPS 偏低和高并发尾延迟未达标；真实 Order/Trade 及 10→50→200租户性能/故障注入仍待集成与验证。Common pilot 使用的是与真正 `com.app.common` Git checkout 版本不同的镜像/JAR，**不得声称本次改动已进入 Common Maven 中央仓库或线上**。生产的24个 `dc-saas-*` 容器维持原样，未运行 GH Actions、未执行GitHub推送。T73实验容器已停止，8个独立证据数据卷保留。

## 工件

源码：`tests/patches/common-rf2-strict-multicycle-t73-20261024.tar.gz`
逐文件 SHA256：`tests/patches/common-rf2-strict-multicycle-t73-20261024.sha256`
整体里程碑：`docs/COMMON_CLUSTER_REQUIREMENTS.md`

**下一关建议**：将目前在演示适配层的旧主隔离、角色反转及最新Custody读写迁移至真正统一Common版本；执行多分区、多物理节点的严格 HA 及高并发限流+批量ACK测试；再进入 Order/Trade 真实委托、成交、资金、持仓、Projection 的整体一致性与HA联动验收。
