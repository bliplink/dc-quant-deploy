# Trade HA：Snapshot Epoch 验收门禁加强（2026-10-13）

## 实机背景

Mac mini Demo 在 11 租户真实交易与 P012 SIGKILL 恢复后，Trade A/B 的
P012 已恢复 Epoch 4、Snapshot Seq 3152、Committed State Seq 3151、
两端 SHA256 相同；ZK 为 Trade B Primary、Trade A Replica、READY。

**这个证明不等于 WAL HEAD/ACK 的持续权威一致性。** 任何自动主切、热更新、
日志清理都必须另行取得复制 ACK 和消费者 durable watermark 证据。

## 修复验收工具中的 Epoch 漏洞

之前 `verify_trade_rollout_snapshot_headroom.py` 和
`check_trade_live_snapshot_role_preflight.py` 比较 Replica 的
Snapshot Seq/State Seq，但若 Replica 来自**旧 Epoch 且 Sequence 更大**，
就可能误判没有落后。实际业务 Trade 恢复器在
`16bca98` 已修复这个问题，验收工具也必须对齐。

现已加 Fail Closed 门禁：

- Source/Target Epoch 或 committed state Epoch 不匹配时，
  snapshot headroom 工具返回 `target_snapshot_epoch_mismatch`；
- 11 租户 ZK 权威分区预检在 Replica Epoch 不同于当前
  Assignment Epoch 时报告 `REPLICA_SNAPSHOT_EPOCH_MISMATCH`；
- 仅在快照属于**相同 Epoch** 时比较 Snapshot Seq 和 State Seq；
- 即使全部 Snapshot 等同，返回状态仍是 `UNPROVEN`，
  `walCommittedHeadAndAckProof=NOT_CHECKED`，不得视为破坏性测试授权。

JavaScript/Java 交易热路径、Gateway 和 TLS 均未更改。
专项回归 `python3 -m unittest discover -s tests -p 'test_*trade*snapshot*.py' -v`
**11/11 PASS**，包含旧 Epoch 高序号、未来 Epoch 高序号、空数据、
同 Epoch 一致但不可自动授权。

## 实机观察与安全边界

在线只读检查再次确认 11 租户 Robot 均 RUNNING，双边盘口正常，
Projection Order/Trade 各 11 水位、无 Event ID 跨分区冲突，
孤儿 Mutation 数为 0（非事务范围观察）。

另一方面，P222 的活跃 Primary 有 Epoch 1、Snapshot Seq 12544，
Replica 暂时只有 Epoch 1、Snapshot Seq 10464：**真实快照暂时落后**。
其自动温缓存有阶段性成功日志（seq 8232、10464），之后出现
`TRADE_REPLICA_WARM_RETRY`，属于可能恢复的后台追平积压，
不能据此推断丢失 WAL、也不能放行额外 SIGKILL。
本次新严格门禁按预期 `BLOCK`；需要继续调查快照传输窗口、
重试阶段以及本地 WAL 的持续提交/ACK 权威数据。

归档盘点显示 516 个 archive 目录、删除授权 0；
物理 GC 保持关闭，直到 Seal ledger、所有 Replica + Projection 水位、
Chronicle Reader generation 与 48 小时保留期独立证明全部满足。
