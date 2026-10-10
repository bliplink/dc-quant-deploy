# Order HA：复制一致性、WAL 归档与安全回收机制（2026-10-10）

**状态：机制设计 + 第一阶段只读盘点工具；自动删除未开发、未授权。** 相关 P0：[OrderSvr #5](https://github.com/bliplink/com.app.dc.ordersvr/issues/5)。不能将现有 `READY`/镜像 CI 通过等同于 256 个分区状态一致。

## 1. 现状和关键结论

- 主站真实隔离集群在 Mac mini 的 Docker 中运行 3 个 OrderSvr 节点、256 个 Order 分区。三个节点各自的 `journal` 目录约 6.4 GiB，其中 `.archive` 的**逻辑文件长度**合计约 3.2 GiB（A 2.08、B 1.08、C 0.03 GiB）；当前只读工具实测三节点归档文件的分配块合计约 **2.46 GiB**（A 1.62、B 0.81、C 0.03 GiB）；文件系统克隆块或预分配可能让这个数与实际可回收空间不完全相同。Mac 数据盘检查时已用 90%，仅剩约 46 GiB。
- `.archive` 由 Chronicle Queue 物理目录重基线搬迁产生，目前**没有自动回收流程**。部分 `.cq4` 预分配，逻辑长度和实际占用不同。活动目录有映射中的 Chronicle 文件，绝不能运行 `rm -rf` 或按 `mtime` 清理。
- P246 复现：旧 Primary 的 archive 包含 `seq 578109 STATE_REMOVE`、`578110 STATE_COMMIT`、`578111 STATE_REMOVE`。副本请求 seq 578110，Primary 当前活动日志从更新后的 baseline 开始；同 epoch 快照接收端保持 GAP。归档的 `STATE_COMMIT` 是恢复依赖，**不能在修复前删除**。
- 当前 Projection 二进制消费者可按需读取旧 `.archive`（`OrderProjectionCommittedReader`），`OrderProjectionDispatcher.assertRetentionSafe` 可检查持久化水位；但它没有参与任何真实的归档 GC。删除前还必须检查副本，快照可恢复、远端备份、读者占用、当前拓扑与合法保留时间。

## 2. 正确区分：副本同步、持久化、历史查询

`OrderSvr` WAL 负责交易状态与崩溃恢复，`ProjectionSvr -> MySQL` 负责可查询的订单/成交历史。不能误把 MySQL 视为 OrderSvr 复制副本，也不能把 HTTP 200/READY 视为 committed 状态。建议统一提交协议：

1. 每分区唯一 Primary，依赖带 epoch 和 assignmentVersion 的持久化租约/栅栏；将客户端提交幂等键绑定 `ClOrdID`、订单及成交事件 ID。
2. Primary 先 WAL append/fsync，再按明确定义的策略要求指定同步副本持久化确认（本系统现阶段按现有同步确认语义；**不要擅自改为多数派确认**）。条件满足时持久化 commit marker/index，才对外确认成功；进度无法证实时返回不确定结果，客户端查询后才能安全重试。
3. 记录独立水位：`journalLastSeq`、`durableCommittedStateSeq`、`commitMarkerSeq`、每个同步 Replica 的 `durableAppliedSeq` 与已校验 state hash、Projection 在持久化 MySQL 后返回的 offset。
4. 分区达到阈值时封闭一致性快照，包含 `(partitionId, epoch, assignmentVersion, lineageId, lastIncludedCommitMarker, committedStateSeq, stateHash, checksum)`；写 `.tmp`，fsync 数据与目录后原子发布。至少有一个能完成离线恢复的快照与其需要的日志链。
5. 同步副本优先通过连续 WAL 补齐 GAP。若发生旧历史分叉/日志已经回收，需要显式 `InstallSnapshot` 握手与恢复证明：控制面授权、确认不存在更高的已提交水位、验证 lineage/epoch/完整文件 checksum、在隔离目录复原并重放、对比 committed state hash，再以原子切换接管；任何验证失败均保持 `NOT_READY`。不能直接复制现网快照覆盖运行中的 Replica。
6. 落后过久且日志已回收的节点，应通过 CAS 成员变更移出同步投票集合，降为 Learner，按快照重建，追平并双向验证后再加入。不得在同一分区产生双 Primary。

### P246 特别注意

同纪元回滚后 **相同 seq 可能有不同历史分支**，所以单靠 `seq <= 最小水位` 回收会有歧义。归档 manifest 必须包含 `lineageId`、commit marker 的 hash，以及回滚/分叉证明。旧分支的 `STATE_COMMIT` 必须一直保留，直到所有仍依赖它的同步副本和 Projection 消费者都通过经过证明的共同提交边界；未提交分叉尾部需要被证明已回收，不可与已提交历史混为一谈。

## 3. WAL 生命周期和归档格式

按每个 **`(partitionId, epoch, lineageId)`** 组织不可变 WAL Segment：

`ACTIVE -> SEALED -> BACKED_UP -> VERIFIED -> RETIRE_CANDIDATE -> TOMBSTONED -> DELETED`

- `ACTIVE`：正在写入/内存映射的 `.cq4`，不可压缩/移动/删除。滚动时独立封闭新 Segment（建议按日与文件大小共同限制），只轮转**物理文件**，不跨越未确认的提交与消费者边界。
- `SEALED`：不再写入，生成 manifest：分区、epoch、lineage、首末 seq、最高已提交 state/marker、SHA-256、字节数、目录身份、封闭时间、创建者版本。对于由 `rebase` 产生的 `.archive`，要显式标记回滚分叉及恢复引用。现有 `Pxxx-epochN-seqM-timestamp` 名称的 `seqM` 只是目录命名信息，**不是 GC 水位证明**。
- `BACKED_UP`：上传到另一故障域的对象存储，如 Cloudflare R2、S3 或 B2；启用服务端加密、版本保留与最小访问权限。Mac 同盘上再复制一份**不算异地备份**。打包压缩只能对已封闭的文件进行，不在活跃 Chronicle 映射文件上直接 gzip。
- `VERIFIED`：重新列出对象并核对 checksum/长度/manifest；周期性从备份恢复到**隔离环境**跑 snapshot+WAL 回放，完成订单/余额/持仓/执行记录抽样或全量对账。
- `RETIRE_CANDIDATE`：过最小保留期，且符合第 4 节所有硬性水位及证明条件。只生成审计候选，**不立刻删除**。
- `TOMBSTONED`：在控制面记录待删版本、分区及 proof ID，等待额外 grace period（建议 24h）；与 Projection Reader/副本 catch-up 取得租约或引用保护，不得在存在活动读者时删除。
- `DELETED`：通过二次检查、操作审计与限速后台 GC，删除已经归档且没有任何依赖的物理文件，并保持至少一个可恢复的远端/本地快照链。逐个节点/分区操作，禁止三个节点同时清除相同历史。

**建议初始值（均须配合证明，不是时间到了即删）**：活动热日志保留至少 24–72 小时；已封闭本地 archive 7–14 天；异地备份 30–90 天，法定审计期和用户数据策略单独配置。也可按 256–512 MiB 的物理 Segment 大小轮转，需先验证 CQ 写入频率、IO、CPU 和快照频率，避免在 Mac mini 上造成 GC/IO 放大。

## 4. 允许删除的硬门禁（全部通过才有资格）

1. **提交证明**：不能缺失或有歧义的 `commitMarker`，archive 所覆盖历史在当前有效 lineage 上已被持久化快照覆盖，或者已有其他已验证 WAL + snapshot 链完整覆盖；有 `GAP` / `NOT_READY` / `ORDER_PARTITION_RECOVERY_FAILED` 即停。
2. **副本证明**：ZooKeeper 拓扑和 lease 版本稳定，每个当前同步 Replica 都已确认安装等价 commit 边界及 state hash；落后节点只能先完成受控移除/降级为 Learner，再以 snapshot bootstrap 处理。
3. **Projection 证明**：必须调用现有的 `OrderProjectionDispatcher.assertRetentionSafe(partition, requiredCommittedStateSeq)`，并查到 Projection 持久化 MySQL watermark；查询失败或 epoch/lineage 对不上即停。切勿仅根据“Projection 活着”判断安全。
4. **备份证明**：目标对象存在、checksum 匹配，且经过可恢复性验证；至少保存一条完整可恢复的快照+增量链。禁止删完本地才发现远端对象不能用。
5. **读者及运维约束**：无现存 journal/catch-up/Projection archive reader 引用；无合法保全/审计/手动故障调查 `pin`；剩余磁盘水位正常；两阶段删除具有 grace period、回滚、日志与审计记录。

对分叉历史，需要 **lineage-aware 的 segment 引用图**，而非所有节点水位的简单数值 `min(seq)`；任一条件未知，都返回 `HOLD`。不允许以磁盘超过 90% 为由绕过这些约束。

## 5. 监控与紧急空间保护

- 指标：`wal_active_bytes{node,partition}`、`wal_archived_bytes`、`segment_gc_hold_count{reason}`、`segment_oldest_age`、`replica_gap_duration`、`commit_vs_replica_watermark_lag`、`projection_durable_lag`、`snapshot_restore_verified`、`archive_remote_backup_lag`、`disk_free_bytes`。
- 建议预警：磁盘 70% 预警；80% 停止扩大新租户和 Robot；90% 触发业务节流、临时降低模拟成交量、外部扩容/迁移并由人工值守。**不能把未确认的 WAL 当作可删除缓存。** 这比“demo=1 无条件不写日志或关闭同步”安全；后者会破坏 HA 数据真实性。
- 压测准入：256 分区一致性 + 无 GAP / NOT_READY，所有活跃 Robot 正常，有可验证 commit/Projection watermark，才能升级租户数量；TPS、延迟和资源必须实测。

## 6. 本轮落地和后续工程顺序

本轮新增只读 `scripts/audit-order-archive-retention.py`：列出每个节点 archive 数量、逻辑大小、实际块分配和目录命名中的 epoch/seq 提示；**所有目录一律 `HOLD`，不支持删除参数**，拒绝 symlink/异常目录与写入 journal 根目录。对应离线单元测试 `tests/test_order_archive_retention.py`，并在 `.github/workflows/validate-order-archive-retention.yml` 运行 CI。

只读实盘验证：共发现 **518 个 archive 目录**（A 132、B 130、C 256），全部标记 `HOLD`，删除授权为 `false`；盘点报告保存为 `/tmp/otc-order-archive-audit-20261010.json`，不包含订单数据或凭据。

下一轮在 OrderSvr 增加持久化 segment manifest、snapshot 安装确认和真实副本/Projection/对象存储的删除证明；先做只读候选列表 + 恢复演练，再以 feature flag 默认关闭的 tombstone/GC 控制器在一次性测试集群验证。P246 恢复完成并全量对账之前，不准对其日志执行归档回收；**本轮不清理任何现网订单数据**。

### 操作示例（只读）

```bash
python3 scripts/audit-order-archive-retention.py \
  --journal "$RUNTIME/data/OrderSvrA/journal" \
  --journal "$RUNTIME/data/OrderSvrB/journal" \
  --journal "$RUNTIME/data/OrderSvrC/journal" \
  --output /tmp/otc-order-archive-audit.json
python3 -m unittest discover -s tests -p 'test_order_archive_retention.py' -v
```
