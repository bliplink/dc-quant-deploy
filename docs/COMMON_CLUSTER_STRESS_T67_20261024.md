# Common RF2 集群压测记录 — T67 / 2026-10-24

## 目标与测试边界

在接入 Order / Trade 之前，对 **现有 Common 真实 A/B Netty + 3 ZooKeeper + 两份持久 WAL/Custody** 开展隔离压力测试。Docker Compose project `otc-t67-stress-fresh`，测试分区 **P000**，两份独立 JVM/WAL 但运行在同一台 Mac / Docker VM。没有真实租户、订单撮合、交易员、资金和持仓；模拟客户端数不是租户数。正式 `dc-saas-*` 服务未修改、未部署，未运行 GitHub Actions。

单机内存 Docker 约 15.58 GiB，多个其他 Demo 服务同时运行，因此结果只是当前机器与配置下的观测值，不是独立机房 HA 或性能上限。

## 阶段 1：初始 Epoch1 严格双 WAL 持久化写入

使用现有 `DemoV19ConcurrentLoadDriver`。每个客户端请求批次包含 **8 次业务等价 WAL 写入**；ACK 显示 `QUORUM_DURABLE_SINGLE_HOST_TEST`。**吞吐量按写入条数统计，延迟按 8 条组成的一批请求统计，两者单位不同。**

| 模拟客户端 | 并发批次 | 请求批次数 | WAL 写入条数 | 写入ACK成功 | 实测写入 TPS | 批次 P50 | 批次 P95 | 批次 P99 | 总时间 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 10 | 2 | 10 | 80 | 80/80 | 13.641 | 608.312 ms | 2765.998 ms | 2765.998 ms | 5.865 s |
| 50 | 8 | 100 | 800 | 800/800 | 55.281 | 774.157 ms | 2462.754 ms | 2980.669 ms | 14.472 s |
| 200 | 16 | 200 | 1600 | 1600/1600 | 69.032 | 1637.230 ms | 2381.925 ms | 2921.826 ms | 23.178 s |

**验证：** 合计 2480 次写入，真实 A 和 B 都持久化了 seq2480、2480 个不同请求，`committedPrefixSha256=7dc987301f645ee8cb58e5ed798bf8be4ffa5800be1d8f6d8d02f602f0165900`，`stateDigest=48bf86899f8913acf9f8e6aaee620949699b9e975c14bd1a02739fd96df6b25c`；未观察到丢失或重复。

内部测量：主节点 Custody 本地 fsync + 签名平均 13.107 ms、远端回执平均 21.788 ms，服务端单批 TCP handler 平均 112.060 ms（样本数 310；该指标不是完整客户端等待时间）。不应据此单独认定根因。

## 阶段 2：SIGKILL A → B 自动接管（Epoch2 单节点降级）

在 Epoch1 seq2480 后直接 SIGKILL A，B 自动完成 `RECOVERING` → `AUTO_DEGRADED_LOCAL_DURABLE READY`，认证上游最新 seq2480，未人工 CAS 选主。B 单机本地 WAL fsync 返回 ACK（**不是双副本 quorum ACK**）。

| B 上写入 | 并发请求 | 成功/尝试 | TPS | 单请求 P50 | 单请求 P95 | 单请求 P99 | 结束水位 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 30 | 4 | 30/30 | 22.949 | 99.531 ms | 296.610 ms | 300.486 ms | 2510 |
| 200 | 16 | 200/200 | 98.351 | 151.169 ms | 223.159 ms | 236.618 ms | 2710 |

**安全说明：** 本地降级 ACK 明确 `quorumDurable=false`，并带 `possibleDataLossIfPrimaryPermanentlyLost=true`；如果尚未恢复复制、B 又发生永久数据损坏，这些客户端已确认数据可能丢失。**不能把此阶段标记为 RPO=0。**

## 阶段 3：A 追平 → Epoch3 严格 READY → 并发压力（关键失败）

重启 A 后，系统自动完成全量最新 seq2710 追平、双物理节点提交证书、双 Custody 和 Epoch3 严格 READY。第一笔新动态请求 seq2711 返回真实 `QUORUM_DURABLE`，`quorumDurable=true`。

- 首次尝试 30 次单条请求 / 并发 4：末尾 `STATUS` 查询发生 8 s Netty RPC 超时，驱动未输出完整成功/失败 ACK 汇总；因此该轮不能认定客户端全部成功。之后观察到 A/B 最终均为 seq2741、状态 SHA 和 WAL SHA 完全一致。这仅能证明服务端最终重放与持久化，不能反推所有客户端都在时限内拿到 ACK。
- 再次尝试 100 次单条请求 / 并发 8：**100 次尝试，仅 1 次客户端收到严格 ACK，99 次客户端 RPC 失败/超时**；耗时 39.110 s，成功 ACK TPS 仅 **0.0256**。请求侧一笔成功延迟 2592.674 ms；最终 `STATUS` 又连续 4 次超时，未能在测量完成时确认最终 seq。
- 严格模式后端日志在客户端结束后还持续打印单笔 `RF2_STRICT_ACK_STAGE`，多条最后阶段耗时 250～1100 ms。并发中 A/B 一度存在短暂水位差，后端在客户端全部超时退出后仍继续执行。**全部服务端排队请求完成后最终 A/B 都为 Epoch3、seq2841、2841 个独立请求**；
  - WAL SHA256：`6e34dc742af9a2e68ba0b879752d06e59e978126bcf01e37063a58c49ee48b4c`；
  - State SHA256：`5f623ff2fbd4e99352482a5cbcf286ae25c3005b67e876791acadb8652e1f50c`。
  - 这证明服务端这次最终已持久化 100/100 笔且A/B一致，**不能把这些最终落盘倒算成客户端在时限内成功确认的请求：客户端仅 1/100 及时收到 ACK**。

**综合判断：性能与客户端可用性 NO-GO。** 前两阶段单分区吞吐可记录，但 Epoch3 动态严格 ACK 在并发 8 下严重退化，不具备进入真实 Order/Trade 交易压力验证的条件。

## 后续修复与重新验收要求

1. **首先分析动态严格 ACK 时的 Netty 队列与线程占用，以及逐请求证书、RSA 验证、双 Custody fsync 耗时**，定位 RPC 为何会在实际落盘成功前后大规模超时；必要时做 Common 内统一批量提交或限流，不能改变 Order/Trade 业务数据层的职责。
2. 保护 `requestId` 幂等；客户端 8 秒超时意味着结果未知，应支持同一 ID 查询/重试，不得重放为新的成交。
3. 维护严格 `QUORUM_DURABLE` 仅在真实 2/2 权威证明后返回；单节点降级 `AUTO_DEGRADED_LOCAL_DURABLE` 必须明确 RPO 风险。不可为了提高 TPS 删除旧主隔离或签名/水位验证。
4. 重新执行严格恢复后 10/50/200 并发，以及**负载中** SIGKILL 主节点和备用节点、角色反转、全进程重启、追平后再压测。验收 TPS、P50/P95/P99、超时率、A/B CommitIndex 与 Custody 头以及业务状态 SHA 一致后，再开始 Order/Trade 真实交易验收。

## 工件

- 源项目：`common-ha-netty-v19-control-cache`
- Compose：`compose.v19-rf2-strict-cutover.yaml` + `compose.t67-stress-fresh.yaml`
- 测试：`DemoV19ConcurrentLoadDriver`、新增的 `DemoV19Rf2StressDriver`（真实客户端逐单 ACK，严格/降级分级）。
- 此报告与源代码仅本地归档于 `dc-quant-deploy`，本轮不部署正式 Demo，不用 GitHub Actions。
