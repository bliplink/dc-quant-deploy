# Trade-B → Trade-A 接管预检与恢复阶段观测（2026-10-12）

## 当前状态（Mac Demo 13:34–13:45 Asia/Shanghai）

- Trade-B 为 10 个活跃业务分区 Primary，Trade-A 为这些分区的 Replica；从 ZK `P023` 实测：
  `primary=TradeSvrB, replica=TradeSvrA, state=READY, epoch=7`。
- 全部 10 个租户的只读业务审计通过：Robot RUNNING、每租户 40 笔活动订单、盘口买卖各 10 档。
- 原有 Order A/B/C 仍运行 Common `361e3e3` 的本地统一镜像。Trade-A 运行 reader-generation `787a211` 的本地候选镜像，Trade-B **仍为旧稳定 `a8fc334` 镜像**。
- 本轮**没有**替换 Trade-B、MD-C 或 Gateway，也没有动 Gateway 转发逻辑，没有清理任何 WAL/开启 GC。

## 新的只读接管阻断脚本

`tests/verify_trade_rollout_snapshot_headroom.py`

严格限制在本地 Trade 快照目录，只读取每个快照最多 64 KiB **元数据前缀**，不会反序列化全量 17–19 MiB 的成交去重负载、不会写入 ZooKeeper/数据库、不会访问订单撮合 API，更不会操作容器。

命令示例（Mac）：

```bash
ROOT="$HOME/.opentradingcore/dc-saas-runtime-zkfix-20261011/data"
python3 tests/verify_trade_rollout_snapshot_headroom.py \
  --source-snapshots "$ROOT/TradeSvrB/snapshot" \
  --target-snapshots "$ROOT/TradeSvrA/snapshot" \
  --min-active 10
```

实机结果：

- `activePartitionCount=10`
- `blockedCount=10`
- `fastSnapshotPreflight=BLOCK`
- `authorizesPrimaryRestart=false`
- `walAndReplicaAckProof=NOT_CHECKED`

举例：

| 分区 | Trade-B 最新快照 seq | Trade-A 本地快照 seq |
| --- | ---: | ---: |
| P023 | 232468 | 9712 |
| P054 | 237006 | 0 |
| P160 | 234966 | 7282 |
| P246 | 228228 | 7896 |

**这不是说 Trade-A 的 WAL 不完整。** 它可能持有完整 replica WAL，
而且日志持续有 `TRADE_REPLICA_HANDLER_SLOW ... failed:false`，说明它在接收复制。
但旧快照需要回放很长的日志才能恢复，在当前 10 分区场景下未经证明能够
快速接管。即使未来两个快照 seq 一致，此脚本仍返回 `UNPROVEN`，
**绝不自动授权重启 Primary**：ZK 权威 assignment、replica durable ack、
commit marker 和隔离故障演练都需要独立验证。

`python3 -m unittest tests.test_verify_trade_rollout_snapshot_headroom -v`：
5/5 测试通过，含快照落后、缺失、不足10分区、读取元数据和正向但未授权情形。

## 新增源码诊断：Trade commit 21aa2f9

仓库：`bliplink/com.app.dc.tradesvr`
验证分支：`codex/trade-safe-wal-archive-canary-20261012`
提交：`21aa2f9b054bffe99c57de91b93f0f4dc1637794`

`TradePartitionLifecycleManager`：
增加每次恢复耗时分解：
`TRADE_PARTITION_RECOVERY_PHASE planMs/applyMs/checkpointMs/rebaseMs/finalMs/totalMs`。
恢复失败时打印耗时而不修改权限/写入逻辑。

`TradeSnapshotStore`：
统一 `save` 与 `saveStreamingDedupe` 的 flush/fsync/atomic-install 逻辑；
增加 `TRADE_SNAPSHOT_IO_PHASE streamMs/fsyncMs/installMs/totalMs`，
可以在下一次恢复中区分 JSON、文件持久化和 rename 具体耗时。
无交易热路径额外 I/O 与锁。Trade **233/233 全量测试通过**。

本地已构建但**未部署**的诊断镜像：
`dc-saas/tradesvr:cluster-dev-local-c361e3e3d-20261012-tradephase-21aa2f9`
Common JAR sha256 仍为
`0ed677b3c57bf65664c209c150570a598b1a9db7a82e63a694e1fe926bf003f3`。

## 现有瓶颈和下一步机制

1. 上次 Trade-A 重启使 Trade-B 多个分区触发严格复制失败；本地 WAL
   留下未提交 `STATE_BATCH`，`TradePartitionLifecycleManager` 必须撤销 READY，
   使用完整、带去重状态的 Recovery Checkpoint 修复脏尾，再恢复 READY。
   该机制保障不把未确认交易误认为已提交，**不能直接绕过**。
2. Trade 的定时 Full Snapshot **仅存在当前 Primary 的本地文件**；
   replica 使用旧快照加持续 WAL。Common 已有
   `SnapshotTransferIntegrity`、`ReplicatedStateMachine` 等抽象，
   Trade 已有 `TradeSnapshotInboundProof` 内容校验，但**没有实际
   分块传输并持久化安装 Replica 完整 Snapshot 的闭环**。
3. **复用 Common 已开发的流式恢复协议**，不重复实现传输：
   `RecoverySourceHeadControlHandler`、`RecoverySourceDataControlHandler`、
   `RecoveryTransferFrame`、`VerifiedRecoveryStagingClient`、
   `StateMachineSnapshotStreams`、`DurableRecoverySnapshotSeal`。
   这些组件已经支持认证 HEAD、逐块读取、校验、暂存和 seal，
   但 **TradeReplicationManager 当前只注册 WAL 复制 handler**，
   尚未装配 source HEAD/DATA control handler、Replica staging/install、
   业务状态机 snapshot/restore 和 READY 门禁；因此还没有形成 Trade 完整闭环。
   服务侧需要严格提供当前物理 Primary、ZK 版本、提交水位和独立密钥来源，
   Replica 只有在身份哈希、partition/epoch、持久提交水位、
   reader 生命周期、原子安装和本地 WAL 覆盖都校验后才可以发布新快照。
   Common 提醒数据控制端口还需要私有网络 ACL 和 TLS/mTLS；
   不得在未配置安全源身份时直接打开明文公网恢复接口。
4. 做单业务分区 B→A 的 CAS+READY 实测，并对照
   Projection/资金/持仓/委托/成交权威结果；
   **通过前禁止直接重启当前承载 10 个活跃租户的 Trade-B**。
5. 后续再接入 Common `JournalArchiveSealCoordinator` 实际 WAL 物理封段，
   异常时保留未完成事务状态；旧 WAL 自动删除继续关闭，
   Gateway 只透传，不需要新增恢复职责。

**不要将“Trade 诊断镜像构建成功”描述为“已完成 HA/自动归档上线”。**
