# T455｜Order P060 旧主毒化、原始 WAL 分叉尾部与自动 Failover Watch 接线缺口（2026-11-03）

## 当前门禁：HA NO-GO（不是交易全站离线）

本审计于 2026-11-03 上午在 Mac Demo 原运行环境上**只读**执行，没有停止 Order/Trade、改 ZooKeeper、清除 WAL、复制/替换客户财务数据或强制发布 READY。

- 当前 DAYWUB Robot `RUNNING`，40 个活动挂单；Trade P144 Projection 与财务 ReadModel 水位曾一起推进到 `66843/66843`，5 个现存财务分区的这两条游标均一致。
- Order A `otc-t432-order-a-restored`、Order B `otc-t453-order-b-standby-parent-watch`、Trade A/B、Gateway、Projection、MD A/B 均运行。**但** Order A 的 P060 不能提供认证 CommitIndex Projection，旧主写入授权也已被 Common 拒绝。
- 禁止将当前业务 RUNNING 误称为 Order/Trade A/B 自动 HA PASS。

## 物理、ZooKeeper 和 Common 代码三方面独立证据

| 核查 | 原始结果 |
|---|---|
| ZK Path | `/dc/cluster/ordersvr-t398/partitions/P060` |
| ZK 当前状态 | `epoch=2, assignmentVersion=2, primary=OrderSvrA, replica=OrderSvrB, state=READY` |
| A 原始 WAL | `285670877` 字节 |
| B 原始 WAL | `285669623` 字节 |
| A 额外尾部 | `1254` 字节，SHA-256 `b6effa278bb05a100078833304ad43248ad95b0186d678354fdb8b134556619d` |
| WAL 前缀 | `cmp` 验证：前 `285669623` 字节完全一致；A/B 完整 WAL 哈希不同 |
| CommitIndex | A 最高 `commit-00000000000000188530.bin`，序号 `188530`；B 作为 Replica 本地无独立 Primary CommitIndex |
| Custody `head.bin` | A/B 文件均为 1010 字节，SHA-256 均为 `8be07c475641f9822531ad8fb7669c187f6316923215736253286b6919c7c361` |
| Custody `receipt-quorum.bin` | A/B 文件均为 1010 字节，SHA-256 均为 `bd92c881612fcbe877f294d999e66bcdcfe0f511dc96a378cad388bee040d17d` |
| 时间线 | B WAL 最后更新 2026-11-02 18:39:43；A WAL 最后更新 20:18:10 |
| 失败节点日志 | A 在 `COMMON_COMMIT_PHASE partition=P060 epoch=2 seq=188531 phase=INDEPENDENT_WAL_FSYNC_RECEIPTS walWriteStarted=true` 后报 `Common poisoned primary Epoch cannot renew`；后来 `CertifiedBusinessCommandRegistry.require(P060)` 持续返回 `Common physically certified partition writer unavailable: P060` |
| 自动 Watch 线程 | Order B、Trade B JVM `jstack` 均无 `common-failover-cold-*` 线程 |

**解释：** 物理字节一致仅说明 B 存储了 A 的完整公共前缀；不等于已经对 Epoch 188530 的签名/CommitIndex/双 Custody 做完新的独立法定验证，也不意味着可以删去 A 的未认证尾部或原 Epoch 重新授权。A 的本地 Grant 已拒绝同 Epoch 写入，ZK 的旧 READY 表示却没有随之撤回。自动故障接管未能闭环。

## 代码层面的确切断点

- Common `CertifiedBusinessCommandBoundary` 在不可确定的物理写入后 `publishPermanentPoison`，把原主 Epoch 标记为永久失权。
- `NodePartitionGrantTable.Permit.requireCurrent()` 第 123–125 行在被毒化 Epoch 上拒绝新的提交/ACK；**这部分保护必须保留**。
- `CertifiedBusinessCommandRegistry.require()` 第 44–47 行在 writer 已毒化时拒绝认证 Projection 读取，所以 Order P060 的投影水位 `2:188530` 无法继续正常读取。这是权限拒绝，不是理所当然的数据丢失。
- Common 提供 `CommonCertifiedNodeRuntime.armAllAutomaticReplicaRecoveryWatches(...)` 和 `CommonCertifiedNodeBootstrap.openAndStartWithCertifiedAutomaticRecovery(...)`，前提是完整本地 Replica census、真实签名 Stage/READY、独立本地追平以及业务状态恢复回调。
- **当前 Order/Trade 应用启动链调用的是** `openAndStartWithZkFencingAndReplayAndSources(...)`，未传递任何 `AutomaticReplicaRecoveryPlan`，检查到的 Java 接线源码没有调用自动 Watch arm API；运行中没有对应 `common-failover-cold-*` 工作线程。
- 因为 Common Failover Coordinator 要求先观察真实旧主存活，再证明旧主 ZK EPHEMERAL lease 已失效，A 当前仍保持节点 lease，不能仅凭 A 本地毒化结果就让 B 无凭据抢主。

## 新增、实际执行的只读可重复门禁

代码：`scripts/audit_certified_ha_partition.py`（`saas-crypto-latest`）。运行示例：

```bash
python3 scripts/audit_certified_ha_partition.py \
  --zk-container otc-t84-source-integrated-otc-ha-zk1-1 \
  --primary-container otc-t432-order-a-restored \
  --replica-container otc-t453-order-b-standby-parent-watch \
  --root /srv/dc/data/t398-ready-v1 \
  --zk-root /dc/cluster/ordersvr-t398/partitions \
  --service OrderSvr --partition P060
```

实际执行返回 **exit 2 / NO_GO**，包括两个独立问题码：
- `ZK_READY_BUT_PRIMARY_PHYSICAL_WRITER_UNAVAILABLE`
- `REPLICA_AUTOMATIC_FAILOVER_WATCH_NOT_RUNNING`

脚本只执行 `docker exec` 对 ZK、WAL 和 JVM 的只读命令以及 `docker logs`；遇到不可查证的状态也 fail-closed 为 NO_GO。绝不将零 watcher 与 ZK READY 伪装为验收成功。

## 修复实施顺序（不可跳步）

1. **只在 Common Demo 验证自动接管启动：** 使用 Common 现有 `openAndStartWithCertifiedAutomaticRecovery` 严格 API 构建每个物理 Replica 的完整 `AutomaticReplicaRecoveryPlan`，计划必须包含独立 E2 WAL/双 Custody 的追平证据、RSA 签名 Stage/READY 和新 Epoch 物理 WAL/业务状态恢复。启动时漏一个 Replica 计划必须 fail closed。不能在 Order/Trade 重写选主。
2. 在 Common Demo 注入 P060 型物理不确定 WAL 尾部：保留 A 多出的原始尾部与哈希、认证序号最高 188530；验证 A 立即撤权；ZK 不再错误声称旧主可用；只有旧节点安全失权、B 物理证明通过、Epoch3 签名恢复并完成认证 READY 后，B 才能被路由为新主。
3. 保证同一进程其他分区的角色处理清晰；不能复用 A 旧 Epoch 的 permit、不能人工修改 CommitIndex、不能直接变更 ZK `READY`、不能以单纯 TCP 恢复替代物理认证。
4. Common Demo 自动 P060 A→B→A 双向真实故障注入完成后，Order/Trade 均改为**同一个 Common 自动启动入口**，保留业务独有的 byte[] apply/snapshot/catchup 回调；先逐节点替换，再检查真实 256 分区、Projection、订单/资金/持仓一致性。随后实际 SIGKILL 和 Home Return 验证。
5. 在这之前，不对正在运行且仍承载交易的 Order A 执行未准备证明的强制停机，因为 B 尚无自动 Watch，停机不会等于自动接管。

**结果：P060 症状、物理尾部及自动 HA 缺口已复现、可检测、可审计；全链 HA 仍 NO-GO。**
