# OpenTradingCore｜Common 业务无关集群边界（架构约束）

更新：2026-10-29。分支：`saas-crypto`。当前 Demo **未通过**完整成交/自动主备验收；此文不代表已部署。

## 必须遵守的职责划分

**Common 的唯一对象是持久化的 `byte[]`**。它可以管理：
- Partition 与节点成员资格、Epoch、Primary/Replica 身份、fencing
- 原始 WAL、TCP 复制、提交序号、证书/Custody 与真实 fsync 确认
- Snapshot/Diff 的存储和请求/恢复、重放、按日期归档与删除
- 节点故障后的授予/撤权、自动互切以及数据一致性

**Common 不能**解析或自行判断订单 GTC/IOC/FOK/PO/DAY/GFD、Limit/Market、开仓/平仓、杠杆/资金/持仓、余额变动、手续费、交易员身份、Robot/Tape、结算是否通过等业务内容。不能靠“允许某类订单才写 WAL”表达物理提交策略。

**Order 自己**拥有 OrderBook、订单与执行、业务状态机、订单类型和交易规则；**Trade 自己**拥有资金、持仓、参数、流水、入金、费用、去重和风控状态。各业务服务用自己的 codec 将**完整、不可变的交易后的状态/事件**编码为 `byte[]`，并实现 apply/replay/snapshot，不把字段格式传入 Common。

## 统一状态提交协议

1. **业务层**：由所属服务验证身份、权限、订单规则及事务前置条件，构造完全确定的 PreparedState（可含任意新增业务域），此时不能修改任何对外可见内存。
2. **业务 Adapter**：按自己的 location+symbol/tenant 路由选择 Common 分区；将 PreparedState 编码为**不透明字节**，调用同一个 `CertifiedBusinessCommandRegistry.commitThenApply(partition, encoded, applyCallback)`。
3. **Common**：只校验物理 Primary/Epoch、分区、签名/证书、WAL 顺序与持久化、故障保护。不识别编码内容或业务事件类型；完成有效持久化后才允许 apply。
4. **业务状态机 apply**：Order/Trade 对属于自己的字节解码并恢复、应用。业务新事件类型必须有**对应的业务 codec、apply 与 replay 实现**。缺失实现要在物理 WAL 写入**之前**拒绝，避免 ACK 后无法重放。
5. **跨服务业务事务**：撮合的 Order 变更与 Trade 资金结算属于业务上的跨服务流程；应使用具有幂等键的业务 outbox/inbox/结算回执和补偿/重试状态。该流程不属于 Common 的业务判断，也不能用绕过结算验证来简化。
6. **故障恢复**：只重放由原有物理证书确认的前缀；未认证的尾部不能直接当作已提交。未认证尾部引起重启失败是恢复机制缺口，要修复自动一致性处理和授予流程，不能靠人工删 WAL 冒充 HA PASS。

## 本轮已核查的实际代码

- Common `CertifiedBusinessCommandRegistry.commitThenApply` 已是业务无关接口，接收分区与编码/回调，并不询问 TIF、订单或资金字段。
- Order `OrderStateJournal.commitPreparedBatch` 虽然称通用批量提交，但对 `Filled` 有业务域限制；`OrderCertifiedCrossPlan` / `OrderCertifiedPartialMakerPlan` 还各自包含业务匹配条件。**这些不能进入 Common，也不应当作为另一套全局“可存储订单类型”白名单**。必须按业务事务的原子性、结算结果重构，并保留安全门禁。
- Trade `TradeStateCoordinator.commitPreparedState` 调用业务域 `TradePreparedStateValidator`，后者当前明确列举余额、持仓、设置、流水、订单等实体。这是 Trade 业务 codec 范围，不是 Common 的允许列表。未来添加业务类型要通过 Trade 业务解码/恢复注册，不需要修改 Common。
- Order/Trade 遗留的 `mutate -> record` 路径必须转换为 `prepare -> physical commit -> apply`。**不能**只删这些保护，否则会出现可见数据已变更但 WAL 未提交的问题。

## 验收门禁

- 任意不同业务类型，只要服务自己的 `prepare + codec + apply + replay` 实现完整，都能经过**同一 Common 物理路径**落盘；Common 无类型分支。
- Order 覆盖 GTC/IOC/FOK/PO/DAY/GFD、Limit/Market、撤单/部分成交/全成交；由**Order 匹配业务规则**决定是否允许成交，不由存储层限制。
- Trade 覆盖余额、资金流水、持仓、参数/杠杆、费用、成交和结算；各域重启前后状态一致。
- 在连续 Robot 报价和 Tape 真正成交期间做 Order/Trade A→B→A 的**自动**主备切换；不允许丢失已确认 ACK、重复成交、双主、旧 Epoch 写入或资金持仓不一致。
- 当前环境 Order A 与 Robot 被停，P045/P180 存在未认证尾部。**不得把文档/单测通过当作上述验收成功**；恢复前必须修复物理机制并检查证据。
