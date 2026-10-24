# Common RF2 严格 ACK 优化与压测记录 — T68（2026-10-24）

## 结论

**单分区 Common A/B 自动 HA 的严格 ACK 性能明显改善，但仍未达到高并发低延迟验收标准；备用节点故障时健康 Primary 不自动降级，完整业务 HA 仍 NO-GO。**

本轮只在一台 Mac 的全新独立 Docker Compose 项目 `otc-t68-strict-batch` 内运行真实 ZooKeeper 3 节点、Netty A/B JVM、独立 WAL 数据卷及两份 RSA/Custody；只覆盖 Common 的 P000。未替换任何 `dc-saas-*` 容器，不是 200 个真实租户，也没有执行 GitHub Actions。

## 已确认的性能根因与修复

1. **每个严格 ACK 重新创建、关闭 Netty 客户端**。对 `DemoV19Rf2StrictAckRuntime.certifyAfterAppend` 的阶段计时发现：一次 8 条的真实签名和双 Custody 约 0.4–0.8 秒，但外层总计 2.4–2.8 秒。额外的约 2 秒来自 `DemoV19TcpClient.close()` 底层 Netty 线程组的优雅退出等待。改为每个物理 Epoch 严格写入运行期复用长连接，不移除真实复制和物理持久化校验。
2. **重复重放历史认证文件**：`DurableWalCommitIndex` 与 `DurableWalCertificateCustody` 曾在每个动态客户端 ACK 时重复打开、锁定与校验历史。改为依据认证 `epoch/config/membership` 或 ZK 版本、PREPARE/READY 区分的独占持久实例；Epoch/版本变化关闭并重新校验。当前实现位于隔离试点，尚未经过生产 Common 发布和完整旧主撤权压力测试。
3. **Common 自带安全批量能力**：复用 `DurableWalGroupCommit.prepareAndCommitGroupForce`，32 条上限使用一次 batch fsync、真实两个物理 RSA 签名和一份连续最高水位 CommitIndex 证书、两份独立 Custody fsync。逐条校验已强制落盘的 `requestId/epoch/sequence/delta`，再用 Common 的 `DurableWalCommitAckGate.requireDurableCovered` 验证受认证最高水位覆盖；仍串行持有物理分区写入锁并双向栅栏。重试原 8 条 batch 返回各 `appliedCount=1`，且 WAL 水位未重复前进。
4. **隔离客户端传输策略**：仅在 `DEMO_V19_RF2_CONTROL_LANES=1` 时，将写入控制 RPC 限定为四条连接，STATUS 独立连接；外部压测 `DemoV19TcpClient(12000)` 与内部 Netty 超时对齐 12 秒。这是试点测量配置，**不是将 12 秒订单 ACK 定为交易 SLA**。测试驱动在 strict 模式下只要有客户端未确认就非零退出，以防错误的绿色 CI。

## Epoch3 严格持久化真实负载

客户端并发数是模拟 Netty 客户端，不代表租户数；ACK TPS 的单位是 **WAL 记录/秒**，P95/P99 单位是**整批 8/32/64 条记录的客户端请求时延**，不能解释为单笔订单时延。

| 方案 | 模拟客户端 | 并发批次 | 每批记录 | 成功/尝试 WAL | 及时 ACK TPS | 批次 P50/P95/P99 |
|---|---:|---:|---:|---:|---:|---|
| 原逐笔严格 ACK（T67） | 100 | 8 | 1 | 1/100 | 0.026 | 大多数超时，不具备代表性 |
| 初始 batch8（T68） | 10 | 2 | 8 | 8/80 | 0.45 | 单个成功样本约 4.36s |
| 复用 Netty 长连接 + batch8 | 10 | 2 | 8 | 80/80 | 10.83 | 0.86s / 2.99s / 2.99s |
| batch8 + 对齐12秒超时 | 50 | 8 | 8 | 800/800 | 27.56 | 2.20s / 4.38s / 4.88s |
| batch8 + 对齐12秒超时 | 200 | 16 | 8 | 1600/1600 | 27.51 | 4.08s / 9.22s / 9.38s |
| **batch32（保留）** | 10 | 2 | 32 | **320/320** | 29.89 | 1.31s / 4.96s / 4.96s |
| **batch32（保留）** | 50 | 8 | 32 | **3200/3200** | **86.94** | 2.71s / **5.47s** / 5.90s |
| batch32（保留） | 200 | 16 | 32 | **5056/6400 及时确认** | **62.67** | 2.07s / 11.62s / 11.95s |
| batch64（实验后回退） | 10 | 2 | 64 | 640/640 | 36.81 | 2.13s / 7.86s / 7.86s |
| batch64（实验后回退） | 50 | 8 | 64 | 6400/6400 | 94.65 | 5.00s / **10.86s** / 11.21s |

批次 64 比批次 32 的 50 客户端吞吐仅提升约 9%，P95 却约翻倍，因此**最终试点代码上限回退到 32 条**。回退后 Java8 重新编译、保留原 WAL 重启 A/B，10 客户端又验证 **320/320 ACK，18.99 条/秒、P95 7.43 秒**；长历史恢复后性能仍波动，应单独测试认证链增长导致的冷启动和尾延迟。

200 客户端 batch32 测试的 **1344 条未及时 ACK** 是客户端超时，而非自动认定丢单。服务端继续执行，最终 A/B 到 **Epoch3、seq13715、13715 个独立请求**，共同 WAL SHA256 `dc27a3db5a428df364288795e6c9dd226274d285d570ca8535b1115847325f36`、业务 State SHA256 `8088ab1b43a6ed57ab4e57038b8f27e959aaeb2efc936fe7b7b3b629e078ce11` 完全一致。后来继续做 64/32 及重启，最终停止隔离容器之前，A/B 都为 **Epoch3、seq21075、21075 个独立请求**，WAL SHA256 `ea9b3f8d5c7421c69b9a073efbdc0004bb055ad42e860d946347d0b38502f06e`，State SHA256 `9dc521c330cf0a92ca782e2d4188128260ca117c7a06702b00d1e3a02cc5c4bd`，完全一致。最后的32条批量代码已通过Java8编译、保留原卷重启后320/320严格ACK再次通过，但高水位下P95达到7.43秒。所有T68测试容器已停止，保留8个证据卷；临时覆盖的Common测试JAR已恢复原始内容，24个正式Demo容器未更改。

## HA 故障边界

- **A 为备份、B 为严格 READY Primary 时 SIGKILL A**：在当前 `QUORUM_DURABLE` Epoch3 下，B 无独立副本签名，严格客户端请求超时/拒绝 ACK，**并不会自动切换到降级的本地持久 ACK**。不能为达到高可用而伪造 2/2 签名。
- A 启动并重新追平后，使用完全相同 `requestId=t68-backup-loss-case` 重试，B 返回严格成功 ACK，`appliedCount=1`，两副本均为 seq3795，SHA256 一致，无重复应用。**但原始请求超时期间的交易可用性没有达成。**
- 要满足用户“备用异常不影响健康主节点”要求，需引入**ZooKeeper Epoch 授权的严格→降级单主切换**，明确 `AUTO_DEGRADED_LOCAL_DURABLE` 的潜在 RPO，并在副本恢复后重新追平、重新认证双物理 READY。该环节当前未完成，不得称 Common 完整 HA GO。

## 下一关与合并要求

保留 batch32、长寿命客户端及认证状态缓存的**隔离实验代码**，尚未替换正式 Common Maven 依赖或生产容器。下一步必须：在全新隔离卷以固定 32 条批次重复 10/50/200 严格压测；定位 200 客户端 12 秒尾延迟并明确限流/请求幂等；实现备份死亡后的正确 ZK 降级授权且重新晋级不丢失严格已确认头；在故障期间注入真实连续写入并测试自动反转、重启及权威一致性。之后才开始 Order/Trade 业务集成。完整的200租户真实订单压测仍未开始。

## 工件

- `tests/patches/common-rf2-dynamic-strict-batch-t68-20261024.tar.gz`：七个完整试点源码/Compose 输入。
- `tests/patches/common-rf2-dynamic-strict-batch-t68-20261024.sha256`：对应文件校验。
- `docs/COMMON_CLUSTER_REQUIREMENTS.md`：整体里程碑状态。
