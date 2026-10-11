# 10 租户 Order 整节点故障 + 跨 Epoch Learner 追平验收（2026-10-11）

## 环境与范围

Mac mini / Colima 隔离的 `dc-saas` Demo，保留原有 10 个租户和数据。始终只使用经验证的本地镜像，不发 Maven Central 或 GHCR。Common JAR SHA-256：

`45ea321a89b44639310f6dd10ac043df144b2be05e8d8c087c0ccba2c01ea6c7`

### 故障注入前

1. `tests/verify-order-cluster-state-host.sh`：256/256 READY，Order B 256 Primary，A/C 为每个分区的同步副本；256 组 Snapshot 一致。
2. `tests/check-demo-tenants-readonly.py`：10/10 Robot RUNNING，每租户 40 单，10 买/10 卖档报价。
3. 独立的只读前置证据写到 `~/.opentradingcore/local-ha-zkfix-20261011-v1/artifacts/order-ten-preflight.json`，10 分钟内有效；未提供显式确认值则故障脚本拒绝执行。

### 真实整节点故障

- UTC 10:34:40：实际 `SIGKILL dc-saas-ordersvr-b`（此前 B 承载**全部 256 个 Primary**）。
- 目标 P238 自动从 B→C、Epoch **2→3**，匹配 `ORDER_PARTITION_PROMOTION_READY`；从测试开始到该分区就绪约 **72.9 秒**。
- Order B 自动恢复启动，原 `unless-stopped` 重启策略恢复。
- 故障原始 JSON：`~/.opentradingcore/local-ha-zkfix-20261011-v1/artifacts/order-ten-kill-20261011T103440Z.json`。
- 故障后全量核验**第一次失败**：P200 的 B 本地 Snapshot Epoch=2，但新 assignment Epoch=3。日志有 `ORDER_LEARNER_REPLICATION_RETRY`，`GAP: new epoch requires SNAPSHOT_BEGIN rebase; localEpoch=2`。此时仅能宣称主节点接管，不可宣称 B 恢复为同步副本。
- 10 租户盘口、400 个 Robot 活动委托、Order/Trade Projection watermark-tail mismatch=0、orphan mutations=0 在故障后仍通过。

### 根因与安全修复

当前旧 sender `OrderReplicationManager.catchUp` 对 Replica 的 `GAP expectedSeq` 总按向前追日志处理。实际 P200 的旧 Epoch 接收端已经到物理 seq=N，新 Epoch 的合法 `SNAPSHOT_BEGIN` 正好在 N 或更早；原 sender 发现请求进度不能增加就失败，导致反复重试、Learner 长期无法成为同步副本。

在最新 Order `saas-crypto` 基线 `e0c87c4` 修复为 `4c7df72`：

- 只有 ACK 明确返回 `GAP` 且声明 `new epoch requires SNAPSHOT_BEGIN rebase; localEpoch=...`，才允许 sender 的 catch-up 起点有界回到经核验的、**当前 Epoch** 的 Snapshot Begin。
- 仍要求本地 Snapshot 元数据、起始序号及 `SNAPSHOT_BEGIN` 事件校验全部成立；接收端仍执行分区 Epoch/Fencing、快照验证、Journal rebase 和 Snapshot 内容校验；**没有放开一般 GAP / 跨 Epoch 安全门禁，也不重写业务数据或水位**。
- 新增复现真实错误的 TCP 集成测试：当旧 Epoch WAL 的物理 Seq 与新 Epoch Begin 冲突时，接收端要求 Begin，发送端重新发送 Begin 和剩余分块，再完成复制。
- 集成测试 **16/16 PASS**；Order 最新全量单测 **323 项、0 失败、0 错误、1 跳过**。
- GitHub 已正常快进推送 `com.app.dc.ordersvr` 的 `saas-crypto` 到 `4c7df72`。

### 部署与最终结果

- 构建 `dc-saas/ordersvr:cluster-dev-local-orderepoch-4c7df72-20261011`，校验 Common JAR SHA 完全一致。
- **B → A → C** 单节点顺序滚动替换，未重新创建数据库或清理租户。每一步核对业务与复制端口。
- 更换期间检测到原有自动拓扑变化，因此停止盲目执行预设顺序，先检查 256 条 ZK assignment；确定 A/C 已分担 Primary 后才继续逐节点滚动，避免误认为仍由 C 单节点承担全部 Primary。
- 更新后完整复测 `verify-order-cluster-state-host.sh`：**256/256 READY、256 组 Snapshot 一致、0 Learner**。A 129 Primary、C 127 Primary、B 256 同步副本；Epoch 分布 128 个 Epoch 2、127 个 Epoch 3、1 个 Epoch 4。三个 Order 容器均运行新镜像，0 OOM。
- P200 实盘 A/B/C Snapshot 均为 **Epoch 3，snapshotSeq=24089，committedStateSeq=24087**；明确出现 `ORDER_AUTO_REPLICA_REPAIRED partition:P200 learner:OrderSvrB`。
- 最终 10 租户全量只读巡检再度 **PASS_10_TENANT_SNAPSHOT**；每个 Robot RUNNING 且 40 单、盘口双边各 10 档。24 个容器运行，Order/Trade Projection watermark-tail mismatch=0、orphan mutation=0、跨分区重复事件 ID=0。
- 最终市场巡检证据：`~/.opentradingcore/local-order-epoch-gap-20261011/artifacts/final-ten-tenant-audit.json`。

## Common 接口与日志归档的剩余收口

**不要把本次修复误判为公共恢复接口已经取代旧逻辑。**

- Common 已有 `ReplicatedStateMachine.apply(byte[])`、流式 `snapshot(ChunkSink)` / `restore(ChunkSource)`、`PartitionStateMachineRegistry`、`StateMachineRecoveryCoordinator`、持久化安装账本与权威状态验证。
- Order/Trade 已实现独立业务状态机适配；但 `*.cluster.stateMachine.commonBinding.enabled` 默认关闭，正常 HA 仍运行旧分区专有恢复路径。Shared Source-Primary 完整认证、持久化检查点、READY 接线未完成全面生产切换验收。不能单纯打开 flag。
- MD 是来自 Order 权威状态的市场数据派生服务，仍需独立可信 Order 快照证明和旧发布者 Fence；其自动接管全路径尚未验收。
- 本次跨 Epoch Snapshot 重基线处理仍位于 Order 业务的复制调度器。下一阶段需把适用于 Order/Trade 的通用 **GAP/NEED_SNAPSHOT** 控制语义抽象到 Common，业务层只实现 Snapshot 与 Apply。
- Archive CQ 文件存在，Trade Archive+Active Journal 的 7 个专项单测通过；**还缺**真实跨归档边界落后节点追平、旧 Epoch 安全归档、保留水位及删除权限的端到端测试。归档审计工具目前禁止删除。

## 下一阶段强制门禁

1. Common 统一的经过认证的快照/增量恢复协调正式接线并与现有 HA 进行影子/分区灰度对比，未获足够证明不得切换全部分区。
2. 在 10 租户环境验证持续真实写入期间的切主，逐笔审计 ACK、orders、executions、资金、持仓、Projection 序号；本轮的 10 租户盘口连续不间断**不足以证明绝对零丢单/零重复成交**。
3. MD 自动接管和 Archive Cross-epoch Catch-up 全流程通过后，才扩大至 20/50/100/200 租户，记录真实订单 TPS、尾延迟、CPU/GC、内存和磁盘 IO。
