# Mac Demo：Common 批量 WAL 认证恢复与真实 Trade WAL 隔离验证（2026-10-13）

> **独立开发及验收记录**：Common/Trade 候选代码尚未合并正式发布分支、
> 未发 Maven Central/正式 GHCR 双架构镜像，未替换运行中的 Trade A/B。
> 本文中的「PASS」仅对应明确列出的离线/隔离测试，不等于 200 租户压测、
> 现网 P222 Replica 追平、滚动重启或物理 GC 已上线。
> 未改变 Gateway，不启用 TLS；Demo 的精确物理节点通信仅位于回环地址。

## 背景 / 已确认瓶颈

Trade P222 的旧版自动温缓存使用 Common 的
`VerifiedRecoveryStagingClient.stage()`：
每条 WAL 对应一次 `RECOVERY_READ_DATA_V2` 控制请求。
真实 Netty 诊断发现：较长 WAL 后缀（1946 条）在数百条请求后被源端拒绝，
122 条后缀成功。Common 源端签名 HEAD 固定窗口 **25 秒**，
认证挑战最长 **30 秒**。旧架构反复验证物理 Primary、ZK 和 Chronicle 单条 WAL，
符合累计请求时长过高的特征；源端故障类型返回通用 `UNSAFE`，
**未单独证明全部失败仅由 TTL 引起**。

此前两份 P222 WAL APFS 克隆已经验证 epoch=1、seq 1..16632
全量连续记录 SHA256 相同；这不是现网实时 WAL HEAD/ACK 的独立证明。

## Common：向后兼容的认证批量 WAL 协议

GitHub 验证分支：
[bliplink/com.app.common/codex/common-wal-batch-recovery-20261013](https://github.com/bliplink/com.app.common/tree/codex/common-wal-batch-recovery-20261013)

- 新增 `RecoveryWalBatchCodec`：最多 **8** 个原始 WAL_SLOT HMAC
  frame，每批总编码大小最多 **512 KiB**；每条仍保留原先完整 MAC、
  物理 Primary、ZK version、Epoch、Sequence、HEAD 和挑战绑定。
  对非法数量、篡改的帧、尾部额外字节、溢出包严格拒绝。
- `RecoverySourceDataControlHandler` 增加显式 `WAL_BATCH=3`
  请求类型，同一个数据读操作中验证请求客户端 HMAC、
  Source HEAD 与最终授权栅栏，响应多个**分别签名**的 WAL 帧。
  `SourceData.readWalBatch` 默认最多 8 条兼容实现，
  允许业务服务覆盖为一次 Chronicle 范围扫描。
- `VerifiedRecoveryStagingClient.stageWithBatch(..., batchSlots)` 
  作为**显式 opt-in**。旧 `stage(...)` 始终委托
  `batchSlots=1`，保证现有单条协议不变。
  响应解包后依然用原有 `transfer.acceptWalSlot()` 和
  `CommittedWalPrefixVerifier` **逐条**核验业务提交边界，
  fsync 整段暂存后仅产出 `VERIFIED_TRANSPORT_ONLY` 证明；
  不安装状态、不赋予 READY、不自动授权接管。
- Common Java 8 全量 `mvn -o test` **240/240 PASS**。
  真实 Netty 端到端测试：
  `RecoveryWalBatchCodecTest` 2/2（HMAC/批次数量负面测试及真实 TCP）；
  `VerifiedRecoveryWalBatchLongSuffixTest` 1/1：
  **2,000 条合成已提交 WAL → 250 次批量 RPC → 已验证暂存 PASS**，
  隔离容器记录传输阶段 **445 ms**。
  该数字不能视为实时生产 TPS 或高负载 SLA。

GitHub 相关提交：
`8584be6`（批量 Codec）、`e86ec9a`（源端）、
`d895203`（接收端）、`950f6d5`（协议测试）、
`d5c97d4`（长后缀 Netty）。

## Trade：一次 Chronicle 读取多条 + 显式开关

GitHub 验证分支：
[bliplink/com.app.dc.tradesvr/codex/trade-safe-wal-archive-canary-20261012](https://github.com/bliplink/com.app.dc.tradesvr/tree/codex/trade-safe-wal-archive-canary-20261012)

- `TradeRecoverySourceDataAdapter.readWalBatch`
  使用 `readRecentRangeConcurrentReadOnly()` **一次**读取最多 8 条，
  保留 Chronicle Reader generation pin，随后严格检查
  Pxxx 分区、连续 Sequence、递增 Epoch、源已签名
  committed HEAD 和单条编码长度。
- Trade Replica 的 `trade.cluster.recovery.replica.walBatch.enabled`
  **默认 false**。只有两个精确物理节点均升级 Common 协议后才可开启
  `VerifiedRecoveryStagingClient.stageWithBatch(...,8)`。
  旧节点继续使用单条传输。
- 新的 Trade 源端缺号、乱序、旧 Epoch、越过签名 HEAD 的
  单测已通过。通过独立 Maven 仓库验证候选 Common JAR，
  不覆盖 Mac 原版 Common：
  **Trade Java 8 全量 297/297 PASS**。
- Trade 相关提交：
  `f5a5a33`（源端优化），`774e2c7`（默认关闭的接收端开关），
  `08cc695`（业务 WAL 防篡改/连续性测试）。

### 构建镜像

本地 Java 8/arm64 候选：

`dc-saas/tradesvr:cluster-dev-local-c6b8fe7d-20261013-walbatch-08cc695`

- Docker image:
  `sha256:d0a524a6a989cc06d6b3c54304728fcf32ccf7db14f4fe2e4a7586210a24cce2`
- Trade commit label:
  `08cc6953fcaf3f0dca3f5677aa34e28357738dfe`
- Common 候选 JAR SHA256:
  `2215a7dc34e86fe0deee82e5d4589ea2cafe8a17cfc5423bbc19524359517e68`
- JRE：Temurin Java 8（1.8.0_392）
- 本地隔离 Maven `~/.opentradingcore/common-batch-qa-20261013/repository`，
  **未更新系统 `~/.m2` 中旧版 Common jar**。
- 此镜像不是 Maven Central / GHCR 的正式可重现发布物，
  不可以直接当线上版本替换。

## 真实 P222 已提交业务 WAL 隔离验证

从原有线上 Trade A 对 P222 的 Chronicle `.cq4` 和完整快照
通过 APFS Clone File 建立**只读时点副本**。
原文件 Clone 前后的 size/mtime 未变化。

- Snapshot epoch=1、snapshotSeq=**25782**，
  committedStateSeq=25781，完整镜像 1,636,406 字节。
- 克隆 WAL 物理末条 seq=**26129**，类型 `STATE_BATCH`，
  **没有对应 `STATE_COMMIT`**。
  隔离测试正确拒绝将其作为 committed HEAD，
  向后定位到已有的 seq=**26128** `STATE_COMMIT`，
  忽略瞬时未完成的 seq26129。
- 取已提交完整后缀 `26128-25782=346` 条，使用
  真实 `TradeRecoveryWalDecoder`、
  `TradePartitionJournal` /
  `TradeRecoverySourceDataAdapter.requireValidWalBatch`、
  Common Signed HEAD、Netty Exact Node 和
  `VerifiedRecoveryStagingClient.stageWithBatch`。
- 认证、完整 Snapshot 下载、346 条实际 Trade
  `STATE_BATCH/STATE_COMMIT` 逐条完整性/业务提交校验、
  暂存 fsync 全部 **PASS**；最多 44 次 WAL 请求。
  隔离容器记录 338 ms 下载时长，
  **无任何业务 apply、READY、在线 Replica 安装、生产数据写入**。
- 文件与 Java8 验证器存于 Mac 私有目录
  `~/.opentradingcore/common-batch-qa-20261013/p222-real-clone`；
  包含真实 WAL 的私有业务副本，不可上传 GitHub。

## 在线集群状态与未完成事项

此轮没有重启 Trade、Order、MD、Gateway，没有真实故障注入。
在线 Trade A/B 仍旧运行 `firstsnap-e249f74` 镜像，
P222 实时 Snapshot：Trade A seq=**25782**，
Trade B seq=**10464**（尚未追平）。
11/11 Robot 只读审计均为 RUNNING，每户 40 活动报价委托、盘口双边各 10 档。
持仓故障测试租户 QGM88N 的 0.0001 BTC 多仓尚未通过 API 确认平仓。

**上线硬门禁**：

1. 先建立独立/受控部署的双节点新 Common + Trade 环境，
   显式开启 `walBatch.enabled=true`，
   复验 `HEAD → MANIFEST → WAL_BATCH → signed staging
   → durable seal/install → Replica 同 Epoch/Seq/SHA`；
   只有通过后才能将候选源码融合到正式分支。
2. 新 Common 必须使用**唯一稳定版本**发布 Maven Central；
   `com.app.dc` 引用该版本，Trade/Order/MD 使用重新编译的
   正式 GHCR `linux/amd64` + `linux/arm64` 镜像，
   不能依赖这次同 Maven SNAPSHOT 版本覆盖后的本地包。
3. 在持仓故障及身份/复制 ACK 严格门禁通过前，
   不重启旧版线上 Trade Primary、不再执行 SIGKILL。
4. WAL 物理归档与 GC 仍需要单独验收：
   持久 Seal、Replica/Projection 消费水位、
   Chronicle Reader generation、保留 48 小时全部完成才可授权删除；
   绝不绕过门禁将删除开关设为 true。
5. 10/11 租户 Demo 运行基线不能替代 50→100→200
   租户阶梯压力测试；尤其不能把 Robot 点价 TPS
   混同于真实订单 TPS。
