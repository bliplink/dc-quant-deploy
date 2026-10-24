# T74：Common RF2 严格 ACK 性能优化与批量实测（2026-10-24）

## 验收结论

**Common 单分区隔离试点的严格吞吐有所改善，但毫秒级 ACK / 1–2k 条每秒的目标尚未达到。** 本轮既测试 1 个 Netty 请求=1 条 WAL，也测试 1 个 Netty GROUP 请求=8/32 条 WAL，**两种请求单位不可混淆**。

沿用 T73 真实 `otc-t71-strict` 三 ZooKeeper + 两个 Java8 JVM、分别持久化 WAL 的同 Mac Docker VM，原 Epoch7 seq96；没有清空旧业务状态、没有切换本地单副本 ACK。

## 本轮实现

源码 `src/main/java/com/opentradingcore/demo/DemoV19Rf2StrictAckRuntime.java`：

- 对真实 RSA 二成员公钥 `DurableWalCommitQuorum.Membership` 做版本绑定缓存，key 包含 ZooKeeper assignment version、Epoch、configuration version 和原主节点。避免 `beforeAppend` 和每笔 `certifyAfterAppend` 重复打开相同的两份 DER 公钥文件、进行 ASN.1 RSA解析与成员摘要构造。配置变更自动不命中。
- 将数据准备/远端 WAL fsync 等等待循环中的一部分重复远端 ZK read，改为对 `DemoHotpathLeaseCache` 本地受限主授权与实时 ZK 链接状态的检查；任何不支持该缓存的模式仍执行原来的实时 ZK read。
- **不替代最终安全检查**：客户端成功前仍重新读取 ZooKeeper 并核对原始 assignment/version，验证远端物理 WAL fsync 与源头哈希、两个独立真实 RSA WAL receipt、原地 durable Common CommitIndex、两份物理 Custody fsync及证书 ACK Gate；关键 CAS、证书落盘前后和最终 Common ACK Gate 仍使用实时 ZK 核验。
- 新增 `DemoV19Rf2GroupStressDriver.java`，用同样真实 Netty `V19_APPEND_GROUP` 请求压测每批8/32条连续 WAL；只统计真实完整的 `QUORUM_DURABLE` ACK，不把本地持久、延迟/超时或半成品证明当作成功。组提交 32 条的界限已经由 Common 累计证书和端点上限支持，本轮没有突破协议上限。

## 真实测试结果

| 模式（Mac / 3ZK / 2 JVM / P000） | 客户端成功 | 严格确认 WAL TPS | P95 |
|---|---:|---:|---:|
| 逐笔、修改前，20请求 / 并发4 | 20/20 | 1.833 | 3489 ms/条 |
| 逐笔、修改后，20请求 / 并发4 | 20/20 | 2.539 | 1994 ms/条 |
| 8 条/group、20组 / 并发4 | 160/160 WAL、20/20组 | 19.840 | 2313 ms/组 |
| 32 条/group、12组 / 并发4 | 384/384 WAL、12/12组 | **71.998** | 2289 ms/组 |

前后两轮逐笔测试伴随 JVM 重启和 Mac 共享资源变化，样本各仅20，不是隔离变量统计实验。因此相对吞吐提高约38.5%、P95 降低约42.9%只能算**本次观测**，不能当作稳定承诺。32条组提交吞吐约72条 WAL/s 但每批仍需约0.2–0.4秒或更长才能双重认证，延迟远超目标；批量吞吐是将固定认证成本摊到32条，而非32条客户端逐笔 RPC。现有客户端并发 200 / 10→50→200 真实租户、物理跨主机和完整 Order/Trade 测试都**没有**因此自动通过。

真实分阶段日志：证书→本地 Custody→远端 Custody→最终 ACK 累计约200–400ms，32条 GROUP 最近几组 `forcedMs` 通常 1–14ms、`certificateMs` 约200–700ms，偶有超过1秒。下一阶段需要把大部分 ZK 状态监测从“每笔同步请求”改成有**真实租约与跨JVM撤权可证明的缓存/事件监听**；优化有界 group fsync 与协议交互，在最终ACK无需降低 2/2 Custody 安全性。这仍是未完成设计/实现。

## 重启与数据一致性

写入合计逐笔40条、8组160条、32组384条，从 seq96 走到 seq680；随后完整重启两个 Java 数据 JVM **但保留原 ZooKeeper / WAL 文件**。恢复原严格 Epoch7 下 `t74-after-both-JVM-restart-strict-1` 客户端 ACK 返回 `QUORUM_DURABLE`，`quorumDurable=true`，`possibleDataLossIfPrimaryPermanentlyLost=false`，到 seq681。A/B 最终均：681条唯一请求，`lastEpoch=7`，WAL SHA256 为 `df3e90c49a0b2453722c3f6fd96eb92a60b58bccd0f39e8a2e70b0c864b52a24`，业务 State SHA256 为 `caf62d4b4114d55069bb1a74973b32eb0dbeadfd07eaff549e52588073f40c2c`，完全相同。Java8 编译及 T73 的25项 HA/恢复 JUnit **25/25 PASS**。

保留项目真实数据卷8个，隔离容器已停止，正式 Demo 的24个 `dc-saas-*` 容器保持运行。未触发 GitHub Actions、未推送 GitHub、未将非Git试点补丁冒充已发布的官方 Common 版本。归档文件 `tests/patches/common-rf2-strict-hotpath-t74-20261024.tar.gz` 包含当前两份完整源码与逐文件 SHA256 清单。

## 下一关

1. 先收口 Common 正式代码中的 ZK热路径与跨JVM撤权缓存，执行逐笔和32条组提交的重复多轮 benchmark，尤其提高 **逐笔低尾延迟**；对高并发下的超时/重复请求按原requestId幂等重试。
2. 多分区与多机扩展性能（256分区，1:1 buddy replica，避免全量 all-to-all 复制），验证多副本签名证书、主备物理故障域、网络隔离和旧主不可复活的真实安全边界。
3. 然后正式合并与本地打包 Common、Order、Trade，执行委托/撮合/余额/持仓/成交和 Projection 水位权威一致性验收，**不是仅凭 WAL 压测就宣布 Order/Trade 可上线**。
