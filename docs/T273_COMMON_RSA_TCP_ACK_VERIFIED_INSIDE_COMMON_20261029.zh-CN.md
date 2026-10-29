# T273｜Common 内部核验 TCP 副本 RSA ACK（2026-10-29）

## 阶段结论

**真实双向 SIGKILL + E3 B 在线回归 + 新写入 TCP fsync 复测 PASS，P0 完整 NO-GO。** T272 之后把 TCP 签名核验从 Demo 测试调用方收归 Common，进一步强化业务代码与集群职责边界。仍不表述为恢复严格 2/2 客户端 ACK。

- Common 工作区 `~/.opentradingcore/t177-common-saas-crypto-integration-20261027`，本地提交 `62560dd`；候选 Jar SHA256 `9e742e1a24092f32bad34b5a4dbf10808d50a7d0e31dc6ae1b9210ed370c68c0`。
- Common `CommonCertifiedDegradedPrimary.mirrorLocalFsyncedRecordToReplica(...)` 现在在**公共包内部**使用 `DurableWalBatchAckProof.read` 验证确切 Node、Epoch、membership、fsynced 原 WAL 前缀 SHA 和 RSA receipt，返回认证后的 `CompletableFuture<DurableWalCommitQuorum.Receipt>`。缺签名/不匹配则完成异常；不让 Demo/Order/Trade 解析或信任原始 Netty ACK；不改变原始 LOCAL 客户承诺。
- 测试控制日志 `~/.opentradingcore/p0-20261029-evidence/t273-common-verifies-tcp-ack.log`，真实隔离 WAL/ZK/Docker 原始证据 `~/.opentradingcore/t124-live-kill-runs/20261029111832`，命令退出码 0。
- 真正 A SIGKILL→B E2 LOCAL READY 40→60→A E2 Replica 回归→B SIGKILL→A E3 LOCAL READY 60→74→旧 B E3 在线身份验签+Replica 回归→A 新 WAL seq3 经原 Common TCP 发送→B 物理 fsync 和 RSA ACK，双方总值 85、7 个去重请求：PASS。
- 本地测试从未获取 C 私钥到 A/B，不改变隔离故障环境之外的业务镜像；没有更改 Common 订单/Trade 内容解析或特殊订单类型约束。

## 尚未通过的最终 P0 门禁

1. `CommonCertifiedNodeRuntime` 在生产常驻生命周期中自主执行 **Watch→恢复→认证→READY**，Demo 测试进程不能继续编排 Common 恢复 API。
2. Common 正式节点自动发现回归成员、自动 TCP 追平和常驻稳态复制，无需故障脚本启动业务特制恢复 JVM。以上 T272/T273 是**隔离测试程序**启动 B 及向 A 发起新业务，不能冒充正式自动重入。
3. 真实授权转换后，未来业务写入的严格 Quorum 签名 ACK 及 2/2 性能/水位一致性，再循环 A/B 主切验证；历史 `LOCAL_DURABLE_ASYNC` 承诺绝不能追认 Quorum。
4. P0 GO 才允许让正式 Order/Trade 使用同 SHA Common Jar 与同一生命周期；禁止任何业务专用集群。依据 `docs/ARCHITECTURE_SIMPLE_COMMON_BOUNDARY_20261029.zh-CN.md`。
