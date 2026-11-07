# OpenTradingCore｜集群可靠性纠偏与交付红线（2026-11-07）

**状态：生效的架构与发布约束。优先级高于历史 Txxx 阶段方案；此文不是“HA 已通过”的验收报告。**

## 0. 为什么必须停下重复改造

在已推进五百余轮任务后，仍然发生了 **正常停掉 Order B/替换镜像，导致原本运行的 Order A 部分分区拒写**。T546 实测：当前 Order/Trade 四个 JVM 仍运行，但 Order A 发生 `Common poisoned primary Epoch cannot renew`，旧 B 重启并没有令相同 Epoch 恢复法定授权；12 个 Robot 仅 7 RUNNING、5 ERROR；六租户 MD/K线真实门禁 3/6，最新交易门禁 NO-GO。这是**生产可用性失败**，不是“还有一点测试没跑完”。

过往存在四类系统性偏差：

1. **复杂度优先于可用性闭环。** 实现了大量 RSA、Custody、Manifest、证书、Epoch 检查，但没有先保证单机持续交易、Replica 正常停机、Primary 继续服务、Replica 自动追平、双方可多次自动切换。
2. **错误外推测试结果。** Demo+Common 的 LOCAL/少分区自动双向切换 PASS，不能外推成现役 Order/Trade 的 256 分区、E2 STRICT、完整生产恢复及滚动升级 PASS；T526 Demo 候选与现役 T520 Common JAR 不一致。
3. **架构边界曾被反复违反。** Order/Trade 被增加业务专属 WAL/ACK/恢复协议；T544 尝试为 ORDER_ONLY 单独新增确认记录，与用户明确的已有 `DefaultExecOrder` 出口冲突。这些设计应废弃，不得并入生产。
4. **发布前置检查缺失。** T546 现役配置 `order.common.nodeRuntime.automaticRecovery=false` 时仍执行 Order B 停机。没有自动接管所需的物理恢复能力，不应该允许滚动发布。这是执行和验收方法失误，不应继续归咎于“最后一个接口”。

**从现在开始，禁止以完成任务编号、单测数量、提交量或 JVM Up 作为可靠性进度。只接受真实客户业务连续性、HA 故障窗口、水位和持久化保证证据。**

## 1. 不可再改变的职责边界

| 层 | 唯一职责 | 明确禁止 |
| --- | --- | --- |
| Common | 节点成员、分区/Epoch/Fencing、ZooKeeper 授权、WAL/fsync、TCP 单向复制、Snapshot/恢复、ACK 合同、自动主备切换、归档；与业务无关的 byte[] 状态接口 | Order 类型、成交类别、余额/持仓意义、特殊 ORDER_ONLY ACK；服务专属选主代码 |
| Demo | 最小可重复确定性业务 byte[] 状态机、真实调用 Common 公共 API 的独立生产接线验证 | 自建 ZK Watch、选主、Epoch、复制、恢复、ACK |
| Order | 订单校验、撮合、业务状态机、业务 Snapshot 编解码、成交历史与统一 MD 成交回报 | 自建 Common 的 WAL/主切/归档/物理证书协议；按业务类型选择集群持久化 |
| Trade | 资金、持仓、结算、风控业务状态机及 Snapshot 编解码 | 业务服务自行实施 Common HA |
| MD | 行情订阅、Snapshot/Diff、最近成交/盘口/K线及业务幂等发布 | 拿交易业务消息充当 Common 控制面 |

**ORDER_ONLY = 现有 DefaultExecOrder；TRADE = TradeExecOrder。** 两者 Order 成交与 MD 历史/K线一致，区别仅在后者执行 TradeSvr 资金/持仓结算。认证 WAL 已应用的 Order after-state，不得再次触发 Default 的订单数量修改。T544 独立 `STATE_MATCH_ORDER_ONLY_NOTIFIED_V1` / 特制 readmodel 方案弃用。

## 2. 明确的可用性与安全合同

- `QUORUM_DURABLE` / STRICT RF2 = 独立两份物理数据副本达到法律上的持久化 ACK 后才可严格成功。B 不在时，**不能假称严格 ACK 继续成功**。
- `LOCAL_DURABLE_ASYNC` = 经 Common 合法新 Epoch / 原主 Fencing / 用户明确授权降级后，单机 fsync 即可继续交易；声明故障丢失未复制、已单节点 ACK 尾部的 RPO 风险。**不得私下把 STRICT 的旧 ACK “补签”成双物理证明**。
- 模式转换应由既有 Common 控制面、真实客户端 ACK 合同明确进行；不能清除 `poisonedPrimaryEpochs`、写假 `READY` 或重启同 Epoch 强行开写。
- 单机和多机用同一套服务公共 API，单机无需额外复制节点，允许以后按 Partition 将指定租户固定到节点；多机只复制到该分区指定副本，不全量广播。
- ZooKeeper 只在控制面，非每笔业务热路径。复制仍为 TCP 单向/异步，可批量 fsync。优先验证可用性、安全和延迟，再谈证明机制扩展。

## 3. 唯一执行顺序（不再分散增加无关功能）

**阶段 A｜恢复可运行的独立环境，不在现役 poisoned E2 上试错。**

- 保存 T546 原始日志及数据卷证据，现役 Order/Trade 不再直接 SIGKILL、强行滚动替换、清空旧 Epoch 或单点改 ZK。
- 若现有 E2→E3 Common 真实物理恢复证据完备，则按 Common 认证恢复；否则在**全新隔离 namespace + 新数据根目录**建立真实新 E1→E2，不重用旧证明或旧分区。不能通过直接重启旧 A 清掉内存 poison 假装恢复。
- 建立可重复的一键 Demo 部署，数据库迁移、配置、端口、镜像/Common SHA、启动恢复、Robot 初始化依次执行；不得靠多轮手工修补才可启动。

**阶段 B｜只在 Common+Demo 用生产同配置完成“最小完整 HA”。**

- 单节点：连续下单、断电/进程停止、重启读取业务 Snapshot + WAL，数据与 requestId 幂等不变。
- RF2：256 分区、128/128 Home。B 正常停机/出错时 A 仍提供所配置的合法服务；自动切换 STRICT→经授权 LOCAL，B 恢复后追平再认证恢复 STRICT；明确中断窗口、TPS、ACK 模式、RPO。
- A SIGKILL→B 新 Epoch 接管→A 从 Snapshot/WAL 追平→Home 自动安全回切→B SIGKILL→A 再接管。连续至少两次，无脚本代替选主；严格 2/2 零已确认丢失，LOCAL 按真实 RPO 报告，不能混淆。
- **正常滚动升级是必须过的独立用例**：先停止/升级 B，确认 A 健康分区持续交易；B 回来全量追平；再轮到 A；还要验证滚动期间 MD/Robot 行情和业务最终一致性。
- 测试必须真多 JVM、真实 ZK、真实持久卷、真实网口；相同 Mac 模拟故障域不能冒充独立物理机可靠性。
- 全部使用**正式打包的同一份 Common SHA**，不允许 Demo 使用最新、Order/Trade 使用旧版；不得使用临时 `systemPath` POM 编译结果宣告正式交付。

**阶段 C｜业务应用只实现公共接口，逐一接入。**

- 同一 Common 固定 SHA，Order A/B、Trade A/B、MD 不再开发自己的 HA；只有 apply/snapshot/restore 与业务数据一致性验证。
- 新租户注册→自动审批→Robot 自动启动→盘口、真实 Maker/Taker 成交→成交历史/最近成交/K线→Trade 余额/保证金/持仓/资金流水→Projection 对账。
- ORDER_ONLY：同样有 Maker/Taker ExecID 与 MD K线，**不执行 Trade 资金变更**。严格防止异步 SQL/MD 入队冒充物理持久化成功。
- 再 10→50→200 租户 steady 与 burst 压测，真实节点故障下注入，记录最大断流、恢复时长、P99/TPS、全量一致性。

## 4. 立即执行的 Stop/Go 机制

- **失败就停**：运行时 `automaticRecovery=false`、Common 物理 SHA 混用、poisoned Epoch、业务写入拒绝、Robot 仍 ERROR、当前 Epoch 生产物理 PlanFactory 未认证，禁止现网滚动升级。
- **发布前必须先确认**正常 B 停机的前驱认证、自动恢复计划、现有分区业务水位、两份独立 WAL/ACK 与 Snapshot，缺任何项保持 NO-GO；不靠“最后一条 JUnit PASS”推翻。
- 每次修复先写：异常日志、唯一代码路径、可重复触发步骤、业务影响范围、预期不变式；确认后最小变更、测试、回滚演练、部署。**不一看到错误就重启或新增协议**。
- 已通过测试分层标记为：`UNIT_PASS`、`DEMO_HA_PASS`、`BUSINESS_E2E_PASS`、`ROLLING_RELEASE_PASS`、`PRODUCTION_READY`。任何层级缺失不得写成最终 PASS；最重要的是后两项。
- 旧 Txxx 结果可保留作证据，不能把失效环境中的 PASS 延用到新环境；所有 NO-GO 必须留档。不可为简单需求继续创造第二套框架。

## 5. 是否放弃自研协议的技术决策门槛

不立即拍脑袋改用 Multi-Raft；先以**限域的架构审查**比较现有 Common 与 Multi-Raft：分区与租户亲和、节点扩容、单机/LOCAL 合同、数据迁移、API 兼容、真实 HA 与运维复杂度。如果自研机制仍无法在同一正式构建下完成真实滚动升级与持续交易，就停止扩充自研 HA 证明体系，评估成熟 Multi-Raft 作为底层替代；迁移不能靠“Raft”名称宣称业务恢复自动正确。

## 6. T546 当前实证基线（供后续对比）

| 指标 | 当前已确认 |
| --- | --- |
| Docker Order A/B、Trade A/B | 都在运行，但 A 部分分区物理拒写 |
| Common 实际 SHA | `b170df0dffd6d8cbeeb64ff3ac9865fe5a89aa803d49580bf0d78eae123801b2`（T520） |
| Common 运行时自动恢复 | Order A/B 都为 `false` |
| ZK 256 分区 | 仍见 E2 READY；不可当作物理恢复证明 |
| Robot | 7 RUNNING / 5 ERROR |
| 六租户 5M K线/行情 | 3/6；其余三租户数据停止更新 |
| ORDER_ONLY 原版 E2E | Y1AM7U 两张 Filled，但历史执行 0，FAIL |
| T546 Order 候选 | 完整 Maven 主/测试源码编译、21 项定向测试及镜像构建 PASS；**未完成安全上线/真实 E2E** |
| 现役恢复计划 | 自动 E2 STRICT→E3 生产接线不完整；**NO-GO** |

证据：`docs/T546_ORDER_ONLY_DEFAULT_LIVE_ROLLOUT_BLOCK_20261107.zh-CN.md`，本机保护目录 `~/.opentradingcore/t546-rollout-evidence-20261107/`；源代码已提交 GitHub `bliplink/com.app.dc.ordersvr:t545-default-exec-unified-candidate`，不得误合并 T544 实验协议。

**交付定义只有一个：真实交易期间 A/B 可安全停机、发布、自动接管、追平、切回，数据满足用户明确的 ACK/RPO 合同。未做到就仍是 NO-GO。**