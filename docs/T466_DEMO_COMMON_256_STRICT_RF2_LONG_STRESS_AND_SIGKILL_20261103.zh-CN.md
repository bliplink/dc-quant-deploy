# T466｜Demo+Common 已进入真实集群压测：256 分区 STRICT 2/2，持续约 5 分钟，双向 SIGKILL 回归

日期：2026-11-03。分支：`dc-quant-deploy/saas-crypto-latest`；Common 的本轮**纯测试 harness**存于独立候选分支 `codex/t466-physical-rf2-256-load-harness`。这份文件是可复核的本地实测记录，不是最终生产 HA GO。

## 1. 测试方式与真实边界

- 机器：Mac M4，物理 10 核；Docker Desktop **8 CPU、约 16 GiB RAM**，与正常 Demo 业务容器共享资源。压测过程中不改现有 Order/Trade/MD/Projection。
- ZooKeeper：正在运行的**三个实际 ZooKeeper JVM**，每次测试使用独立 `/dc/cluster/t117-t466-...`（单 P090）或 `/dc/cluster/t466-...`（全 256）命名空间；不接触旧 T398/P060。
- Common：**两个物理独立 Docker JVM**，A/B 各有独立 RSA 私钥、WAL、CommitIndex、Custody 和 Receipt Ledger。Netty 真实 TCP，单节点不可虚报另一节点成功。
- 确认模式：只记录 `DurableWalCommitAckGate.Confirmed` 真正返回的 **`QUORUM_DURABLE`**。严格 2/2 的 CommitIndex/Custody/RSA/fsync 链路在每次写入后完成。客户端成功还需 Demo 状态机 Apply 成功。
- 256 分区分配：P000–P127 Home Primary A/B Replica；P128–P255 Home Primary B/A Replica。每个节点 128 主+128 备、同一原始 Home。负载按分区路由，各分区独立锁和 WAL。
- `10/50/200` 表示**模拟逻辑请求组/身份**，不是注册了 10/50/200 个真实 SaaS 租户；E1 新 Genesis / BusinessRecoveryReady 使用**隔离测试启动入口**，不是正式双 RSA 封存的生产首启或真实资金/持仓。
- 任何失败/超时都不能当成成功客户 ACK；测试按分区校验精确 seq 连续、原始 WAL framing、两个不同物理磁盘的 SHA-256 与逐字节相等。所有 256 分区（包括 0 写分区）必须匹配。
- 不使用 GitHub Actions，不清旧数据，不修旧 P060 未提交尾部。

## 2. 测试二进制和执行方式

唯一 Common JAR：
`dc-quant-deploy/.work/t449-common-gw-rejoin/target/t465-common-real-physical-sources.jar`

SHA-256：**`a0de1fb65d29e6ec6d2a9741c8b621c959c5bc3c63b1c7fcd5266c415fdc7c19`**。

每次都拷贝为 **run-specific immutable JAR**；大负载后的磁盘验证使用同一 SHA 的二进制。T465 Common 源码正式 HEAD `5f04c8325fa1294eb28d7824093d05c6e09561ca`。本轮仅新增 Demo 压测代码/脚本，没有修改 Common 生产的复制、签名或 ACK 规则。

新增/调整的测试代码：
- Common 测试候选 `codex/t466-physical-rf2-256-load-harness`：
  - `examples/common-only-demo/src/test/java/com/opentradingcore/demo/DemoCommonStrictRf2Load.java`
  - `examples/common-only-demo/src/test/java/com/opentradingcore/demo/DemoCommon256StrictProcess.java`
  - `examples/common-only-demo/src/test/java/com/opentradingcore/demo/DemoCommonLiveZkProcess.java` 只增加显式 T466 性能入口/副本持有时长；候选文件包含此前未合并的 T456 测试工作，**不能覆盖正式 Common main 代码**。
- 部署仓正式 `saas-crypto-latest`：
  - `tests/run-t466-demo-common-strict-rf2-stress.sh`
  - `tests/run-t466-demo-common-256-strict-load.sh`
- Java 8 本地编译 PASS；脚本 `bash -n` PASS；源文件 `git diff --check` PASS；不依赖 Maven/GitHub Actions 的远端构建。

## 3. 实际五轮压测：累计 55,310 笔严格双节点成功

| 类型 | 写入数 | 真实结果 |
|---|---:|---|
| 单 P090 10/50/200 基础 | 270 | **270 ACK / 0 失败**；A/B 原始 WAL 完全一致 |
| 单 P090 持续/突发 | 3,700 | **3,700 ACK / 0 失败**；末段 40.50 TPS，P95 414.3 ms，P99 554.0 ms |
| 完整 256 分区 128:128 基础 | 540 | **540 ACK / 0 失败**；完整 256 A/B WAL 检查 PASS |
| 完整 256 分区持续/突发 | 7,400 | **7,400 ACK / 0 失败**；末段 A 67.19 / B 67.17 TPS，P99 295.6 / 275.0 ms；全量 WAL PASS |
| 完整 256 分区约 5 分钟连续运行 | 43,400 | **43,400 ACK / 0 失败**；A/B 各 21,700，约 316 秒，**256 分区全部原始 WAL 完全一致** |
| **累计** | **55,310** | **55,310 个严格 2/2 ACK，0 失败、0 seq 缺口/重复、0 分区物理分叉** |

真实全 256 持续运行，第 4–7 阶段四轮各每节点 5000 笔、8 并发：

| 阶段 | A TPS | B TPS | A P99 (ms) | B P99 (ms) |
|---|---:|---:|---:|---:|
| 第一轮 5000/节点 | 73.17 | 73.28 | 311.54 | 293.73 |
| 第二轮 5000/节点 | 72.32 | 73.12 | 285.10 | 273.51 |
| 第三轮 5000/节点 | 67.67 | 67.27 | 365.81 | 371.40 |
| 第四轮 5000/节点 | 68.57 | 68.59 | 317.98 | 309.52 |

两节点同时工作，最后一轮总吞吐约 **137 ACK/s**（A 68.57+B 68.59）。半程后吞吐下降约 6%–8%，P99 一度增加至约 371 ms；不能宣称长期吞吐没有退化。实测 Docker 容器每 JVM CPU 约 100%（约一个核），RSS 约 200–272 MiB，整个 Docker 配置为 8 CPU/16 GiB；当前主要受分区逐笔顺序提交和串行物理协议成本限制，而非全部 8 核打满。

**代码路径原因**：`CommonCertifiedBusinessApplyBoundary` 同分区互斥，`CertifiedBusinessCommandBoundary` 逐次等待严格提交，`DirectNettyCertifiedBusinessTransport` 有独立的远端 WAL fsync/RSA 回执、远端 Custody 安装、远端 Custody receipt-ledger 三道串行 TCP/持久化操作，并有本地 WAL/CommitIndex/Custody fsync。不能删掉这些证据“优化”性能；如优化须用带严格签名覆盖边界的 Common 物理 batch/group commit，经过完整 SIGKILL/一致性测试才合入。

### 5 份指标和原始 WAL 路径

1. `dc-quant-deploy/.work/t466-common-rf2-stress/20261103151258-45350/metrics.json`（单热点基础）
2. `dc-quant-deploy/.work/t466-common-rf2-stress/20261103151510-45503/metrics.json`（单热点持续）
3. `dc-quant-deploy/.work/t466-common-256-strict/20261103152159-45807/metrics.json`（256 基础）
4. `dc-quant-deploy/.work/t466-common-256-strict/20261103152247-45978/metrics.json`（256 持续）
5. `dc-quant-deploy/.work/t466-common-256-strict/20261103152854-47015/metrics.json`（256 长时间）

后者内含 **256 分区两独立磁盘每个原始 WAL 的 SHA-256**；校验标记：
`T466_256_REAL_A_B_256_PARTITIONS_BITEXACT_PASS frames=43400 partitions=256`。

五次结果均来自本机日志和独立 Python 重读 JSON：`T466_ALL_FIVE_RUNS_FULLY_VERIFIED_STRICT_ACK_SUM=55310`。

## 4. 压测之后再做自动双向 SIGKILL（独立 Common P090）

复用**同一 T465 SHA**，在独立 Demo 三 ZK namespace 上真实执行：
- E1 A/B 双原始 RSA 和物理 WAL 2/2；
- 真实 `SIGKILL A` → Common B 自动 Watch E2 RECOVERING → 原始 Genesis/Snapshot/WAL 认证 Replay；
- C 独立 RSA 见证 E2 LOCAL READY，B 继续写（**RPO 风险，quorum=false**）；
- A 回来从 B 认证 WAL 追平、仅作 Replica；
- 真实 `SIGKILL B` → A 自动 E3 恢复并写，B 随后重新加入；
- B E3 Common Netty 接收 A 新 WAL 并真实 fsync。脚本退出码 **0**。

证据目录：
`/Users/kong/.opentradingcore/t124-live-kill-runs/20261103233504`。
最后结果 `T272_B_E3_COMMON_TCP_NEW_WAL_FSYNCED_PASS`。这里 **E2/E3 仍为 LOCAL ACK，不能追溯或未来声称 STRICT QUORUM**。

## 5. 下一道真正 HA 门禁仍 NO-GO

**不能把 256 分区无故障压力 + 单分区自动故障回归拼接成“256 分区自动 HA PASS”**。正式目标未完成：
1. Common 对真实 256 分区实现各自的 RSA 签名恢复源、独立 Replica Catchup、可信原始 Home、原 Epoch 撤权/退休、E+1 Snapshot/WAL/CommitIndex/Custody、业务 Apply 和新严格 2/2 READY；故障在负载过程中 A/B 互相 SIGKILL、回 Home，全链路 256 一致、无双主。
2. Order/Trade 仍缺少真实 `SourceEvidence`、原始 Home 身份与 `DurablePhysicalRecovery` 生产实现；T465 Spring HMAC 与 Common 真 WAL/Snapshot 已通过，但正式四镜像还没构建/替换。不能以 Demo 测试替代。
3. 上述真实业务 HA 成功后再**用全新 ZooKeeper 命名空间与空业务数据卷**快速重部署 Demo，重新注册 10→50→200 **真实 SaaS 租户**，真实自动审批、Robot 持续报价、Tape 点价、下单成交、余额/持仓/成交/Projection 一致性；至少 2–3× 5–10min burst，记录恢复耗时、P95/P99/TPS、磁盘归档/自动清理。

本轮隔离容器已全部清理，原 Demo Order A/B、Trade A/B 容器持续 Up；旧 P060 WAL 未恢复或修改；不使用 GitHub Actions。
