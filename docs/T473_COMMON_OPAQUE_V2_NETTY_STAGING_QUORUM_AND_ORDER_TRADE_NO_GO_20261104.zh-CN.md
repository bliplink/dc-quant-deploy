# T473｜Common v2 原始 WAL 跨 Netty Staging 回归与业务接线阻塞（2026-11-04）

## 结论
**Common v2 原始物理 WAL 跨 Netty 数据传输与认证 Staging：测试 PASS；完整 Order/Trade E2/E3 真实业务 HA：NO-GO。** 不得将本次通过误报为 256 业务分区故障自动主切、真实资金一致性或故障期 RPO0 验收。

## GitHub 本次代码
- [Common saas-crypto-latest 6f528b9c37fc55fd17b4c632822bd07c5a1d8fd4](https://github.com/bliplink/com.app.common/commit/6f528b9c37fc55fd17b4c632822bd07c5a1d8fd4)
- 上一轮基线 [Common 05c204102009b962beba8e5b36feed24ed721366](https://github.com/bliplink/com.app.common/commit/05c204102009b962beba8e5b36feed24ed721366)
- 全部代码在 Common 原有 WAL/Netty/Snapshot/Prefix/Staging/Coordinator 实现内修正，未新增选主、Replica 复制、独立服务或 READY 机制，也未增加 Order/Trade 业务语义判断。

## 经实际源代码确认的根因
1. 正常 Order/Trade 业务写入采用“一条业务 frame 经 Common 严格物理提交”的 WAL 模式；旧 Staging 则强制 `STATE + STATE_COMMIT`，把 final WAL record 解释为提交标记，导致即使物理 WAL 提交水位正确也不能恢复。
2. 原 SourceData 将业务 payload 而非完整 `CommonFileBusinessWal` 原始物理 envelope 传给远端，因而接收方无法计算与物理双 RSA fsync 水位一致的完整 original WAL digest。
3. Order/Trade 本地自动恢复 Spring 接线引用 `orderCommonPersistedSignedSourceEvidence` / `orderCommonCertifiedPhysicalRecovery` 和对应 Trade Bean，但所检查的工作区源码尚无真实提供者定义；这部分仍需实际实现并验证。

## 代码变更
- CommonFileBusinessWal 增加只验证原始二进制 WAL 结构/CRC 的解码入口；**解析合法不代表有提交认证**，认证仍完全取自 Common 双物理 RSA + 双 Custody 提交水位。
- CommonCertifiedPartitionRuntime 为已经物理认证的 Source WAL 区间读取原始帧，与原业务 payload 做一致性对比；提交前后再次认证精确 HEAD。
- CommonCertifiedSealedSourceData 对显式签名协议 v2 输出 **original WAL envelope**，v1 继续保持原返回语义；CommonCertifiedOpaqueRecoveryWindow 相应校验原始物理帧而非将业务 payload 当 WAL 哈希材料。
- RecoveryQuorumCommitAttestation.Prefix 显式 v2 独立签名域；terminal SHA 代表最后一条原始已提交 WAL 帧，不伪造 `STATE_COMMIT`。必须有不同物理节点的独立 voter keys，且 quorum 与 Signed Source HEAD 的协议一致。
- VerifiedRecoveryStagingClient 增加 `stageOpaqueWithSourceManifest`，复用原有 Netty HEAD/Manifest/Data 和恢复 Prefix 控制 RPC。分别在跨网读取前、后要求独立来源的 Prefix 物理多数票，核对完整 Snapshot SHA、原始 WAL frame CRC/序号/Epoch、原始区间摘要和尾部 frame SHA；Staging 中保留原始 frame 以供同一个 StateMachineRecoveryCoordinator 按业务解码 Apply。旧 v1 Staging 保留。
- RecoveryStagedQuorumBoundary 接受独立认证的 v2 原始 WAL 区间，保持旧 v1 路径并且不授予 READY。
- 新增 RecoveryOpaqueV2QuorumReceiptTest、VerifiedOpaqueV2NettyStagingTest 以及真实 CommonCertifiedPartitionRuntime 原始帧篡改拒绝断言。

## 验证证据
1. JDK 8 编译修改后 Common 核心类与 JUnit 通过。
2. 原有 Demo RSA 密钥、真实 Netty A/B 物理 CommitIndex/Custody 和磁盘 Snapshot / WAL 的 9 项回归 PASS，包括原始完整 WAL 读取、CRC 失败拒绝、非零 Snapshot + 物理提交帧 Apply、NOT_READY。
3. 使用真正 127.0.0.1 Netty 连接、两个独立物理身份 HMAC Prefix 控制 RPC、签名 HEAD/Manifest 与磁盘 Staging 的 **v2 网络回归 1/1 PASS（11.256 秒）**。业务记录、Snapshot 与签名证据提供者是**测试夹具**，不是正式 Order/Trade JVM；测试正确拒绝篡改后 Staging 数据，且未开放 READY。
4. 12 类相关 Common 旧/新协议与物理运行回归 **58/58 PASS**，包括上述网络测试和 9 项物理 RSA 测试；日志位于 Mac `.work/t449-common-gw-rejoin/target/t473-regression-real.log`。另有 v2 quorum 独立测试 2/2 PASS。
5. 本轮没有重新运行完整 Demo 双 SIGKILL 或 256 分区压力；T472 已由相同上一版候选 JAR 完成测试，本次新 Netty 源码变更不能沿用旧 JAR 测试直接宣称相同镜像的全面故障切换通过。

## 后续必须完成
- 将 v2 Source/Manifest/Prefix 与真正业务 Snapshot **durable lineage** 接入 Order/Trade Spring 依赖，严格依据各自真实已应用业务状态和 Common 物理提交证明，禁止空 Bean、伪造提交水位、自动授予 READY 或额外业务集群机制。
- 使用本轮新版 Common 新构建 JAR SHA，在隔离 Demo 重新执行真实 A→B→A SIGKILL/E2/E3、持续写入、Replica 追平及多分区负载，然后同版 Order/Trade 启动与真实业务资金/委托/成交/Projection 一致性验证。
- 若任何前置验证失败则保持 NO-GO，不替换运行中四个业务容器。P060 旧数据保持不动。
- 本轮核对四个 Order/Trade 容器处于 Up 状态；**未触碰容器、未清理 P060、未用 GitHub Actions**。

**最终状态：T473 Common v2 跨 Netty 认证 Staging 测试 PASS；OpenTradingCore 真实 Order/Trade 完整 HA 仍 NO-GO。**
