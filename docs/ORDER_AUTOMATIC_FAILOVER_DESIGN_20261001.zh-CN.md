# Order 自动接管与副本失联继续接单：实施门禁

> 状态：设计与验收计划，**未实现、未部署**。2026-10-01 的 P110 真实业务 A→B→A 仅验证受控 assignment 切换，不是节点失联自动接管。

## 当前事实

- Order A/B 采用 256 个分区、ZooKeeper assignment、`SYNC_PER_RECORD`、本地 journal/snapshot、复制 ACK 和 commit-aware promotion。`OrderPartitionLifecycleManager` 轮询 assignment，并在完成恢复及 promotion barrier 后开放本地主分区。
- assignment 的故障检测、选主和 epoch 推进仍靠操作脚本。当前双节点同步模式在副本失联时，`OrderReplicationManager` 的复制发送或 promotion snapshot transfer 失败，相关分区拒单。2026-10-01 在当前 `sha-943b6dd` 镜像的独立 Colima 栈中实测停 A、手动 CAS 改派 B：B 因缺必需副本而 fail-closed；A 回来并完成 snapshot rebase/恢复屏障后才 READY；返回 A 后路由和复制复测通过。证据在 `/data/dc-saas-order-cluster-dev/evidence/20261001-120638-node-failure-recovery/result.json`。这不是自动继续接单。
- 两个 Order 容器位于同一 Mac mini。它们能隔离单 JVM 故障，不能把同机断电、磁盘损坏或 ZooKeeper 单点故障算作已解决。

## 必须明确的可用性与数据承诺

1. **健康双节点同步**：客户成功回包前，命令和状态/commit 边界必须有本地持久化与副本 ACK；目标是单个节点故障下已确认订单不丢。
2. **主节点失联、原副本存活**：只有在确认原主已被新 epoch 围栏、原副本持有可验证的 committed prefix、无不可裁剪的未提交尾巴之后，才能自动升主。控制面不可判定时拒单，不能靠 TCP 超时直接选主。
3. **副本失联、原主存活**：新增显式的 `failClosed`（默认）与 `localDurableDegraded` 两种策略。后者只能在控制面确认失联并记录降级 epoch 后接单；客户回包需明确“已本地持久化但未复制”的耐久等级。若这个唯一存活节点随后损坏，降级期间已确认订单可能丢失；因此**不能同时承诺“无副本继续接单”和“任意后续节点故障 RPO=0”**。
4. **异步模式**：单独配置、单独披露可能的数据损失窗口、队列上限和背压；不能把它的吞吐或恢复结果混作同步模式的 RPO 证明。

## 实施顺序

1. 在可复用集群层增加受租约保护的 controller：基于 ZooKeeper session/ephemeral membership 判定节点状态，使用版本 CAS 改 assignment、单调递增 epoch、强制旧主撤销本地 readiness；选主时校验 journal、snapshot、commit watermark。controller 失联或 ZK quorum 不足时停止改派。
2. 给 Order promotion 增加两条分开的安全路径：有健康副本时维持现有复制 snapshot barrier；经 controller 授权的单节点降级 epoch 则做本地持久化 checkpoint，并记录 `DEGRADED_LOCAL_DURABLE`，不伪造副本 ACK 或复用普通 `READY` 语义。新主接单前必须检查其 committed prefix 覆盖所有可证明的客户成功边界。
3. 复制层按当前 assignment/epoch 决定同步 ACK 门槛；仅显式降级 epoch 可跳过不可达副本，且 journal、state、commit 的本地 `fsync`/回包顺序须有测试证明。每笔降级成功结果应可审计并在 API/运营侧可见。
4. 故障节点重返后先作为 learner：从权威 snapshot + committed delta 追赶，校验 hash/sequence/watermark，再转 replica。降级期间不得自动抢回 primary；恢复双副本同步与普通耐久等级后再解除降级告警。

## 隔离环境验收矩阵（不得先在当前全量业务环境停节点）

| 场景 | 期望 |
|---|---|
| 正常 A/B：提交后立刻杀主 | B 自动升主；已确认 GTC 订单可查可撤；旧 A 重返不得重复执行或抢主 |
| 正常 A/B：杀副本，默认策略 | 主对受影响分区拒新单；其他分区按其副本状态工作；无假 ACK |
| 正常 A/B：杀副本，显式降级策略 | controller 改降级 epoch 后主可继续接单；回包标记本地耐久，journal/state/commit 本地恢复正确 |
| 降级期间主再损坏 | 明确 RPO 风险或拒绝承诺；不能把可能丢单报告为通过 |
| 旧节点重返并携带旧 epoch 写入 | 必须被围栏；只可 learner 追赶，hash/水位核对后恢复同步副本 |
| ZooKeeper 断连、误判心跳、双 controller 竞选 | 不得双主接单；同一分区最多一个有效 writer |
| 256 分区并行恢复与 Robot 连续补单 | 记录检测、选主、恢复、READY 的 p50/p95/p99；核对账务、投影水位、活动单和重启/OOM |

## 当前下一步

隔离栈的**当前行为基线**已跑通：路由/同步 ACK → 停 A → 缺副本拒单 → A 恢复后 B READY → 切回 A → 路由/复制复测，随后隔离容器已停止并保留证据。下一步才是在隔离栈实现 controller、显式降级模式和剩余故障矩阵，再考虑当前业务栈的单分区灰度。Order 接单阶段计时镜像 `c595bfc` 也尚未部署；当前 63 个活跃租户与 39 个非零持仓下，诊断发布需完整 A/B 围栏、Trade 配套重启、256 READY、业务和投影回归，不应单侧热换。
