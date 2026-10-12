# Mac Demo 10 Tenant：Trade 新主 epoch 快照刷新与安全接管门禁（2026-10-12）

## 结论与真实运行状态

Mac 本地 24/24 容器正常；10/10 租户 Robot RUNNING、
各40笔活动委托，双边盘口各10档。
Robot bounded Tape 修复后，10户资源检查再次
`BASELINE_READY_ONLY`，CPU PSI=11.91%，Robot
CPU quota使用率约10.79%，没有不活跃租户或恢复告警。
**这些不是实际订单TPS，也不授权自动扩到200户。**

Order 的 `verify-order-cluster-state-host.sh`：
256/256 READY、epoch=1，A/B各128 Primary，C是256
Replica，`snapshot_sets_equal=256`，无进程重启。
需要认证的逐业务接口扫描仍未替代完整资金/成交审计。

## 精确的 Trade 安全阻塞：10/10活跃分区

部署脚本新增只读工具：
`tests/check_trade_live_snapshot_role_preflight.py`。

输入：最新 `PASS_10_TENANT_SNAPSHOT` 审计 JSON（15分钟
以内）、实时 ZK 256分区全量 assignment，以及
A/B 物理 `snapshot/Pnnn/latest.json` bounded metadata。
不是仅根据奇偶分区猜Primary；以当前ZK为唯一角色来源。

检查：唯一租户映射、分区READY、主从不重叠、
当前Primary的Snapshot是否同epoch和非零业务水位、
Replica是否包含当前租户、Replica Snapshot的水位
是否落后或超过合法epoch。
每次都明确输出
`authorizesPrimarySigkill=false`、
`authorizesReplicaRestart=false`；
即使快照相同，也不能把这个证明当成权威
同步ACK、已签名Committed HEAD或者跨容器恢复。

本轮实机结果：
`checkedTenants=10`、
`snapshotBlocked=10`、`decision=BLOCKED`。
大部分 Replica 保留不含当前租户的启动空快照；
P159 曾真实执行两次角色反转，旧Epoch快照与当前
新的ZK Epoch仍不完全一致。
其它十租户尾部 `STATE_COMMIT` 已有独立只读
Chronicle WAL主从字节相等采样证据，但
**不能从此推出本次SIGKILL一定会及时恢复**。

测试：
`python3 -m unittest
tests.test_check_trade_live_snapshot_role_preflight
tests.test_verify_trade_rollout_snapshot_headroom`
共8项通过。
Mac私有证据：
`~/.opentradingcore/local-ha-clean-20261012-v1/
tenants-live-trade-HA-snapshot-role-gate-validated.json`。
新的工具会拒绝缺失/陈旧的租户审计和不完整ZK目录，
并且只读，不会操作业务数据。

## 机制改进：已提交的Trade源码和候选镜像

Trade源码分支：
`bliplink/com.app.dc.tradesvr`
`codex/trade-safe-wal-archive-canary-20261012`
提交：
`e3e3e6384da257c2a9fc4a92c385ab4cf5954f36`。

在 `TradeSnapshotScheduler` 增加当前ZK已READY、
主节点内存提交状态属于 **当前epoch** 且有新业务
commit 时的快照优先更新机制：
避免P159等经过角色反转的分区继续等待
`minCommittedMutations=20000`才更新。
还加入epochDue调度优先级，单次仍只选择一个分区。
`TradeSnapshotManager.captureLocked` 本来已经验证
不允许不干净的未提交journal tail、degraded、
non-primary或恢复中的分区；**没有放松约束**。

新测试在隔离本地 Common 6b8fe7d Maven
依赖链上 `mvn -o clean test`：
**289/289项通过，0 fail/error**。
标准Trade源码POM仍指旧`com.app.dc`版本，
不能不经依赖发布直接执行新源码的中央仓库正式编译。

固定本地候选（不在在线A/B上部署）：
`dc-saas/tradesvr:cluster-dev-local-c6b8fe7d-20261012-epoch-snap-e3e3e63`

Common jar SHA256：
`34a6ee05db748eb2990f68b1dc86188a41ca52c320e1838b9cd82fd3c77a0363`，
镜像 labels `dc.common.jar.sha256` 与
`dc.source.revision` 已核实匹配。
编译产物和 Maven 全量报告在 Mac 私有
`~/.opentradingcore/local-ha-wal-seal-20261012-v1/artifacts/`。

## 为何没有滚动替换新候选镜像

Trade A/B为双节点Primary/单强制同步Replica，任一
节点承载部分Primary并充当另一侧全部Partition
Replica。`trade.cluster.replication.required=true`，
若滚动重启唯一Replica，可能导致原Primary无法
获取持久ACK和故障后的慢追平。

更关键：虽然已开发签名HEAD+Snapshot Manifest+
已提交WAL验签分块传输+本地fsync sealed cache
的公共/Trade adapter，当前
`TradeReplicaWarmSnapshotScheduler` 默认关闭，
**跨Docker容器安全TLS/mTLS尚未完成**。
该调度器明确拒绝没有加密的Docker IP直连；
`trade.cluster.snapshot.periodic.recoveryTransferAware`
也尚未在线开启，近期同步尾部可超过Common V2
的4096 WAL slot单次传输上限。

不能通过直接复制在线Replica JSON、放开明文
TCP、关闭同步ACK或者偷偷清空业务数据来绕过
校验。新版本仅是离线候选；应先落地可信跨容器
传输及Replica持久HEAD/commit marker验证，
完成离线恢复到READY接管测试后才能安排容器
替换和带持仓SIGKILL。

## 仍未通过

- Trade带真实持仓自动SIGKILL→epoch切换→资产一致性；
- MD自动主切（Order最新完整市场镜像及发布fence缺失）；
- 业务WAL安全归档和自动GC的全端水位门禁；
- 真实Order TPS及50/100/200户压测；
- 新Trade候选正式Maven公共包/GHCR多架构发布。

Gateway仅透传，无业务改动。现网10租户仍在运行。
