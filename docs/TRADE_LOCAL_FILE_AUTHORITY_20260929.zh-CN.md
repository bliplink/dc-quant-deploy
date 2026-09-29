# Trade 本地文件权威恢复与数据库 Projection 边界

日期：2026-09-29。对应 TradeSvr 本地候选代码；**未替换运行镜像、未重启节点、未做故障注入或业务晋级**。

## 目标与当前改动

Trade 的交易状态（余额、持仓、账户交易配置、用户合约配置、订单镜像、执行幂等状态）以本地快照和已提交分区日志为恢复来源；MySQL/RocksDB 的业务表只能是查询投影或旧模式兼容物，不能在权威模式下填补恢复缺口。AdminSvr 的合约定义订阅属于外部产品配置，不是这些用户交易状态的数据库回退。

候选代码在 `trade.cluster.recovery.authoritative=true` 时：

- 启动不调用四项 DAO 加载：`loadAccountBalance`、`loadPosition`、`loadAccountConfig`、`loadSymbolParas`。Legacy/非权威模式保持原启动路径。
- 启动前要求分区日志、提交标记、严格状态提交、快照和生命周期门禁都开启；本地无快照且无已提交事件的分区拒绝 READY，错误为 `TRADE_LOCAL_RECOVERY_BASELINE_MISSING`。不能把空目录当成历史为空，更不能从 SQL 投影“补齐”后晋级。
- 真正有已提交日志或经明确建立的本地快照时，沿现有恢复器重建；快照/增量会覆盖同分区内存，不读 DAO。明确的空快照只适用于可以证明此前从未有业务状态的全新分区；**不能对旧分区随手生成空快照**。
- `READY` 仍只表示当前程序的分区恢复门禁，不自动证明财务效果、跨节点复制提交、RPO=0 或 API 可交易。

合成测试把 DAO 设置为“一调用就失败”，覆盖无 DAO 启动、失去文件时拒绝、空快照的有限语义、只有提交日志恢复、快照加提交增量恢复及旧模式隔离。Trade 全量 57 个测试类/221 个用例通过；尚不是线上数据正确性证明。

## 为什么不能现在晋级镜像

两个既有隔离日志副本 P204/P122 的重放审计显示账户配置和用户合约配置记录数均为零。**这不等于线上一定有配置丢失**；它只说明这些日志不能单独证明自定义杠杆、逐仓/全仓、双向/单向及专属费率已经被覆盖。历史订单镜像也有 60,208 条无状态的 Trade 片段，已另行定位。把当前候选直接部署，可能把正常业务的配置静默回退为默认值；不允许用数据库投影自动填充并伪称本地恢复成功。

本次只收紧恢复的来源和失败语义，没有改变订单费用/PnL 公式，没有修改旧日志，没有在生产生成空快照，也没有宣布历史账实一致。

## 仍然违反完整 Projection 分层的路径

启动来源修正不等于“Trade 不再直接写数据库”。当前源码仍可见：

| 路径 | 当前行为 | 改造约束 |
| --- | --- | --- |
| 普通余额、持仓和交易配置变更 | `ITradeDao` 的异步/事务写入 | 先确保业务结果经本地提交日志 durable，再为 ProjectionSvr 实现幂等业务表物化；不得先删 DB 调用导致查询/状态缺失 |
| Posting/资金流水 | 普通余额更新可调用 `persistAccountBalanceAndPostings` 数据库事务 | 日志需携带完整不可变 posting 及唯一 ID；Projection 可重放、去重和校验余额与流水，不能只写余额最终值 |
| Funding | `applyFundingSettlement` 使用数据库事务/去重 | 将结算时点、去重键、余额/持仓/流水作为一个权威提交单元；数据库失败不应决定核心交易结果 |
| 保险接管与 ADL | `coverLiquidationDeficit`、`BankruptcyTakeoverRepository`、`PositionAdlRepository`、`PendingPositionAdlRecovery` 使用 SQL 事务/查询 | 重建保险基金、接管、ADL 剩余量/执行去重的文件权威状态机；保留原有财务原子性和幂等，再迁出事务 |
| 历史查询 | `getPostingReport` 从 DAO 读 | 留在 Projection 查询面，不参与核心状态恢复/风险决策 |

当前 ProjectionSvr 的 `TradeProjectionService` 消费 Trade committed binary stream，把原事件和 mutation 存入 `dc_trade_projection_event` / `dc_trade_projection_mutation`，并在同一事务推进独立 watermark。**它还没有把这些 mutation 物化为 `dc_users_balance`、`dc_orders_position`、`dc_users_config`、`dc_users_symbol_config` 或 posting 等业务查询表。**现有这些表仍依赖 Trade 直接写入；因此现阶段不能关闭 SQL 写入并宣称 Projection 已接管。下一步必须实现业务表物化、历史回放/重建与逐表一致性校验，再逐条消除旧双写来源和先后顺序冲突。不能通过仅设置 `dbType=rockdb` 解决——那仍是另一套 DAO 持久状态，不等于分区快照+提交日志权威。

候选 ProjectionSvr 代码现已增加**默认关闭**的 `projection.trade.configTables.enabled` 首个切片：账户配置和用户合约配置的 UPSERT/REMOVE，可与事件归档及 watermark 在同一事务中应用，校验 location/user/security 键与 payload 一致，不把业务值拼进 SQL。它不是历史回填器，也未覆盖余额、持仓、posting；未经过全量历史重建/双写退场前，**不得在运行环境开启该开关**。上段关于“还没有物化”的表述指当前运行环境及完整业务表集，不能把这个默认关闭的候选切片算作已接管。

第二个**默认关闭**的候选切片 `projection.trade.coreTables.enabled` 现在能从 `ACCOUNT_BALANCE` / `POSITION` 完整后态 mutation 生成租户隔离的 UPSERT/REMOVE，在同一事务内执行。它按既有业务表精度校验，不接受越界/缺字段并阻止 watermark 前进；未覆盖 posting、funding 去重、保险/ADL 的专属状态，也未做真实数据库事务/历史回填验收。ProjectionSvr 全量 8 个测试类 / 33 个用例通过，不能据此开启开关或停用 Trade 的 SQL 写入。

## 发布门禁与顺序

1. 用只读证据确定每个老分区的起点/缺口和业务配置来源：日志、可信本地快照、Order 已提交状态与独立账务记录交叉核对。SQL 只用来比较投影滞后/差异，不能作为自动修复的唯一权威。
2. 对历史缺口制定明确迁移方案并离线演练；尤其要验证订单终态、执行去重、资金余额/流水和所有客户自定义配置。缺口不能证明时保持 NOT_READY，不能反向写库或生成伪空快照。
3. 先让 ProjectionSvr 从已提交 mutation 幂等物化普通余额、持仓和配置业务表，并校验历史回放；然后才分模块迁出 Trade 直接 SQL 写：普通交易/配置/Posting → Funding → 保险与 ADL。每一步要有文件重放、Projection GAP/重启、重复事件/网络分区、失败注入和业务计算一致性测试。
4. 准备全量 A/B 节点容量、复制提交权威来源与只读/Risk 门禁，再按单分区隔离试验和可撤回镜像逐步晋级；压测只在业务与恢复门禁通过后进行。

因此当前部署不变。不能仅凭单节点本地文件存在就宣布安全切主；副本追平、epoch fencing 与已确认提交的来源证明仍是独立门禁。
