# OrderSvr 受控滚动升级：只读预检门禁（2026-10-10）

## 当前约束

OrderSvr 目前将 256 个分区分别安排在 A/B 两个 Primary 上，A/B 各 128 个，C 没有 Primary。三个节点运行 `SYNC_PER_RECORD`，调用 `replicateToAssignedReplicas` 时逐个校验**所有被分配副本**的复制 ACK；配置还要求 `minimumLiveSynchronizedReplicas=2`。因此，直接 `docker restart C` 并不天然安全，可能阻塞其他租户的下单；重启 A 或 B 还会扰动至少 128 个 Primary 分区。

ZooKeeper 的 `READY` 代表分配状态，不足以证明业务状态 READY。P246 的 ZooKeeper 为 READY，但网关持续返回 `PARTITION_NOT_READY`；复核 768 份 A/B/C 快照发现仅 P246 不同，不能从这 255 个相同快照进一步推断全部运行时提交水位已经达成一致。

## 已执行的只读门禁

`python3 scripts/check-order-rolling-upgrade-preflight.py --output /tmp/order-upgrade-preflight-20261010.json`

只执行 ZooKeeper `get`、Docker `inspect/logs`、宿主机配置和快照文件读取、磁盘余量检查，**不包含** `set`、`restart`、`kill`、`rm`、`compose up`、快照替换或 ZooKeeper 变更。结果 JSON 永远写入 `canRestartOrderNodes=false`、`canEnableP246Repair=false`，因为此工具并不能验证“写入已完全排空、实时已提交 WAL 水位、Projection 持久化水位、回滚计划”四项严格门禁。状态为 `BLOCKED` 时退出码为 2；读取或解释失败退出 3，均不能用作准入。

### 2026-10-10 实盘观察

| 检查 | 结果 |
| --- | --- |
| ZooKeeper 256 个分区 | 全部 READY，但不代表运行时健康 |
| 当前 Primary 数量 | A 128，B 128，C 0 |
| 三节点 Snapshot | 768 份，唯一不一致 P246 |
| 复制配置 | `SYNC_PER_RECORD` / 全副本 ACK / 最少 2 个同步副本 |
| 最近 60 秒错误告警 | 616 行匹配（包含重复警告，不是 616 次故障） |
| 数据盘 | 约 91.52% 已用，超过 80% 发布警戒线 |
| 实际结论 | `BLOCKED`，不允许升级或打开 P246 修复 |

输出只包含安全统计数字、镜像引用及异常分区号，不输出客户订单或登录凭据。

## 解决升级风险的工程策略

1. **先建一次性集群**（隔离 ZooKeeper、网关、三节点 Order WAL、分区及访问凭据），重演 P246 的 WAL seq 578109/578110/578111，在新镜像中仅将 `archivedCommitRepairEnabled=true` 和 `archivedCommitRepairPartitions=P246` 赋给测试实例，验证恢复正确、隔离租户成交/资金对账、旧快照副本追平、再造出同样故障并验证回滚。
2. 实现正式升级原语（二选一）：**写入排空**（包括 Robot + API 订单、撤单和异步队列、所有正在执行命令的 ACK），或带 CAS/epoch 栅栏的**副本/Primary 成员迁移**（确保剩余两台仍能完成原同步确认条件）。不能简单降低 `minimumLiveSynchronizedReplicas`、切为异步复制或把 Order C 的副本资格直接删掉。
3. 前后采集当前有效 lineage + `committedStateSeq` + `commitMarkerSeq` + 每个 Replica 的持久化复制确认/状态 hash，核对 Projection 已写入 MySQL 的 watermark、成交记录、余额、持仓和未结委托。检测到任何冲突立即保持 `NOT_READY`。
4. 有验证过的旧镜像回滚策略，确保**不覆盖 WAL/归档或在线快照**。备份到独立故障域后仍需离线恢复演练。升级必须经过有原子性保证的流量停写/重新开放原语，不能只是运行本预检或“CI green”。
5. P246 恢复、256 分区运行状态及权威对账成功后，再解除 Robot 压测门禁；自动 WAL GC 独立继续保持禁用，直到日志持久化清单、副本和 Projection 水位、远端备份可恢复性均已证明。

## 代码与联动事项

- 只读预检：`scripts/check-order-rolling-upgrade-preflight.py`；离线正反例：`tests/test_order_rolling_upgrade_preflight.py`；工作流：`.github/workflows/validate-order-rolling-upgrade-preflight.yml`。
- [OrderSvr P0 #5 同纪元 GAP](https://github.com/bliplink/com.app.dc.ordersvr/issues/5)、[P1 #6 安全滚动升级](https://github.com/bliplink/com.app.dc.ordersvr/issues/6)。
- [P246 故障报告](ORDER_HA_P246_RECOVERY_BLOCKER_20261010.md)、[WAL 归档安全回收](ORDER_WAL_SNAPSHOT_ARCHIVE_RETENTION_DESIGN_20261010.zh-CN.md)。

已为实际的 `deploy-saas.sh` 入口增加 **OrderSvr 不可变镜像 ID 保护**：如果已存在运行集群并拟部署不同的 OrderSvr image ID，在执行任何 `compose_up -d` 之前立即 `die`。没有已存在节点的 fresh-install 不受此保护影响，同一镜像 ID 可以继续做其它 SaaS 服务的常规更新；在集群已经存在时，不能借助主站升级顺路切换 OrderSvr 镜像。对应 6 个发布脚本模拟测试覆盖 A/B、无 Primary 的 C、未启用的集群以及首次部署。该限制暂时没有旁路开关。它仅检测**镜像变更**，不能证明同镜像重新加载配置、滚动重启或业务写入排空是安全的；后续还必须实现真正的成员迁移/排空协议。

**注意：本门禁刻意不提供“允许升级”代码路径。只有真实写入排空/安全成员迁移机制及其权威验收完成后，才能额外设计可授权的上线控制器。**
