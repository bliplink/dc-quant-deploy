# Order / Trade 公共集群 Durable ACK 与 Chronicle 恢复联调（2026-10-14）

## 状态与版本

以下均为 **Draft / staged 未发布**，代码已提交，未把任何生产服务替换成该版本：

| 代码库 | 修复分支/PR | 验证 |
| --- | --- | --- |
| Common | [bliplink/com.app.common#11](https://github.com/bliplink/com.app.common/pull/11) | `DurableReplicaAckGuard`、271/271 Java 测试、[Actions PASS](https://github.com/bliplink/com.app.common/actions/runs/38523475670) |
| com.app.dc | [bliplink/com.app.dc#6](https://github.com/bliplink/com.app.dc/pull/6) | 暂存 `0.0.5-SNAPSHOT` → `Common 3.0.21-SNAPSHOT`，保留 JDBC8 依赖排除 |
| Trade | [bliplink/com.app.dc.tradesvr#8](https://github.com/bliplink/com.app.dc.tradesvr/pull/8) + [#9](https://github.com/bliplink/com.app.dc.tradesvr/pull/9) | Journal 冷启动、倒序 Tail、快照 WAL 屏障、Common 持久 ACK、235/235 Java 测试，跨仓库 [CI 原版 PASS](https://github.com/bliplink/com.app.dc.tradesvr/actions/runs/38523702302)；最新完整前缀补丁再检 |
| Order | [bliplink/com.app.dc.ordersvr#10](https://github.com/bliplink/com.app.dc.ordersvr/pull/10) | Journal 完整前缀校验、真实物理索引、归档回滚证明、Common 持久 ACK，372 tests/0 failures/0 errors/3 skipped，三仓库 [CI PASS](https://github.com/bliplink/com.app.dc.ordersvr/actions/runs/38525430682) |

发布链：`Common 3.0.21-SNAPSHOT → com.app.dc 0.0.5-SNAPSHOT → Order/Trade staged Maven build`。它不是 Maven Central 正式版本，**不得使用相同 SNAPSHOT 二进制冒充已发布 3.0.20，也不得从 Mac 本地开发镜像直接上线**。

## Common 状态机抽象边界

1. Common 管复制分区规则、ACK 成功许可、Epoch/角色二次检验，独立维护已有 `RecoverySourceHeadControlHandler`、`StateMachineRecoveryCoordinator`、Snapshot/Diff<byte[]> 和归档退休认证。
2. `DurableReplicaAckGuard.acknowledge()`：新批次 **OK** 和已存在批次 **DUPLICATE** 均必须完成业务 Journal 提供的 `requireDurableThrough()`，校验同步前后角色 Epoch 和连续序号；任意失败只能返回 ERROR/GAP，绝不能返回成功。Common 不识别业务 Payload。
3. Order/Trade 各自实现本地 Chronicle 存储序号、真实物理映射块同步 `MappedBytesStore.syncUpTo(SYNC)`、实时 assignment Epoch 检查，不能通过改 Gateway 达成恢复；Gateway 继续纯透传。
4. 当前按**每个复制批次**同步一次，不在每个 record 上做独立 fsync；需要用 Robot 10/50/200 与故障注入证明 p95/p99 及崩溃持久性。跨 Chronicle roll 文件的前缀同步、ZooKeeper 控制面掉线时 assignment 缓存鲜度也需要实测，不能用单个 msync 调用夸称整个集群无丢单。

## Chronicle 冷恢复根因与修复

现网 Trade 日志显示 9 个分区的 `snapshotSeq > runtimeJournalLastSeq`。官方 Chronicle Java API 在离线 WAL 副本证明：`queue.lastIndex()` 有时停在第一条记录，而实际正向 Tailer 仍能连续解码大量记录。Trade P200 原读 282051，真实物理末尾 284052；P071 原 309369，真实末尾 311962。两节点仍没有到达最新快照（P200 284088/P071 312034）。其余 9 分区快照末端共 **474 序号**尚未在两节点 WAL 中找到原始记录，是否取得 quorum durable ACK 尚未认证。**这不是 474 笔订单丢失的结论。**

单纯 `moveToIndex(queue.lastIndex())` 后正向扫描也不够：若该 hint 指向最后一条，可以跳过它**前面**的 WAL 序号断裂。Order 新增故障注入式 Java 回归测试证明旧算法会错误接受该场景。最终 Order 和 Trade 都改为在**分区冷启动**校验整段 Chronicle 正向连续记录，以及 baseline 的下一条序号；启动时缓存真实物理尾部索引，追加时更新，倒序和定位基于真实索引。正常交易、撮合、复制热路径不执行全量扫描。

Order 的归档回滚证明额外读取**精确** STATE_COMMIT 序号及前一条 state，不信任归档 CQ stale lastIndex。Trade 的定时快照与恢复 checkpoint 在写文件前执行 WAL 边界 msync；这是快照持久化屏障，与 Replica ACK 持久性不互相替代。

严格扫描在真实 P200 和 P071 的隔离副本上确认仍读到 284052/311962；**未启动生产 Trade 新镜像、未执行 force READY、未删除任何 WAL 文件、未改 Gateway**。

## 当前现网（2026-10-14 15:02 CST）

- Order-A/B 老镜像；Order-C 候选 `dc-saas/ordersvr:common-3020-jdbc8-20261014`；Trade-A/B 老镜像。
- Robot：**2 RUNNING、9 ERROR / RUNTIME_FAILURE**。
- macOS 宿主盘使用率约 **94%**，余 **29 GiB**；WAL/archive 磁盘清理必须等待真实 HEAD、Replica 与消费水位认证。
- ZooKeeper READY 不代表业务已恢复。不要把九个 Trade 分区未通过的恢复计划强制置 READY。

## 上线前明确 NO-GO

1. 用 Common 的可信源端 HEAD/新鲜 ZK fencing 和**完整市场快照及 Diff**对 Trade 9 分区缺失的提交边界做权威修复，证明业务状态、资金持仓、Projection/Order watermark 和执行去重一致；否则拒绝恢复。
2. Order/Trade 冷启动 256 分区完整前缀扫描会增加重启成本，需采样启动 I/O/时间并优化 Chronicle checkpoint 元数据，但**不允许用未认证的尾部索引跳过校验**。
3. durable ACK msync 对跨 roll 的持久前缀证明、双副本 crash / Power-cut / SIGKILL、Epoch 变更期间缓存鲜度、高负荷延迟都必须通过；可能需要 Common bounded group-commit，在不降低持久性时再优化。
4. 经过 GitHub Actions 正式构建/发布 Common 唯一新 Maven Central 版本，更新 com.app.dc，服务基于其构建多平台 GHCR；逐节点 Canary → 全分区 READY、Robot 正常 → HA failover / catchup / role reversal → 才允许归档日志按安全水位自动删除。
5. Open issues: [Order #9](https://github.com/bliplink/com.app.dc.ordersvr/issues/9)、[Trade #7](https://github.com/bliplink/com.app.dc.tradesvr/issues/7)。不得宣称 Demo 已完成上线。
