# Trade 本地文件权威恢复与数据库 Projection 边界

日期：2026-09-29。对应 TradeSvr 本地候选代码；**未替换运行镜像、未重启节点、未做故障注入或业务晋级**。

历史本地候选镜像（均未推送/部署）：TradeSvr `sha256:646c20379813dd9c09da4bbe469fc48fffd9a70f718b8258a711b495b36f2624`（源码 `480ddad`），ProjectionSvr `sha256:f3cf8b70d6422e37dafcf4f015a9491ee624c8f4eabf7e64b6801bfed9bfadfe`（源码 `5209b2d`）。关键 class 当时与本地产物一致，但不证明完整依赖来源或运行/财务验收。**后续发现旧 Projection 候选使用 common 3.0.13/旧 bridge，与本轮 Maven 解析的 common 3.0.14/bridge 不同；该旧镜像不得复用为本轮验收产物，需重新构建并核对完整依赖。**只读运行节点核查：Trade A/B 均沿用旧镜像 `sha256:a740926...`，各 128/128 当前主 READY 日志证据；ProjectionSvr 仍为旧镜像 `sha256:c761d1f...`，三容器 0 restart、OOM=false。READY 证据不是业务可写验证。

## 目标与当前改动

后续候选增量：Trade `40ae10c` 已补原结果持久记录与快照/日志恢复索引（STATE_BATCH v2 / snapshot v3）；270 项测试通过。旧现金入口和 SQL 先写路径未接入/未退场，当前 Projection 明确拒绝 v2，不能把局部恢复候选当作线上现金幂等完成。见 [本轮验证及下一步门禁](TRADE_CASH_REQUEST_RECOVERY_CANDIDATE_20260929.zh-CN.md)。

Trade 的交易状态（余额、持仓、账户交易配置、用户合约配置、订单镜像、执行幂等状态）以本地快照和已提交分区日志为恢复来源；MySQL/RocksDB 的业务表只能是查询投影或旧模式兼容物，不能在权威模式下填补恢复缺口。AdminSvr 的合约定义订阅属于外部产品配置，不是这些用户交易状态的数据库回退。

候选代码在 `trade.cluster.recovery.authoritative=true` 时：

- 启动不调用四项 DAO 加载：`loadAccountBalance`、`loadPosition`、`loadAccountConfig`、`loadSymbolParas`。Legacy/非权威模式保持原启动路径。
- 启动前要求分区日志、提交标记、严格状态提交、快照和生命周期门禁都开启；本地无快照且无已提交事件的分区拒绝 READY，错误为 `TRADE_LOCAL_RECOVERY_BASELINE_MISSING`。不能把空目录当成历史为空，更不能从 SQL 投影“补齐”后晋级。
- 真正有已提交日志或经明确建立的本地快照时，沿现有恢复器重建；快照/增量会覆盖同分区内存，不读 DAO。明确的空快照只适用于可以证明此前从未有业务状态的全新分区；**不能对旧分区随手生成空快照**。
- `READY` 仍只表示当前程序的分区恢复门禁，不自动证明财务效果、跨节点复制提交、RPO=0 或 API 可交易。

合成测试把 DAO 设置为“一调用就失败”，覆盖无 DAO 启动、失去文件时拒绝、空快照的有限语义、只有提交日志恢复、快照加提交增量恢复及旧模式隔离。Trade 全量 57 个测试类/222 个用例通过；尚不是线上数据正确性证明。

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

第二个**默认关闭**的候选切片 `projection.trade.coreTables.enabled` 现在能从 `ACCOUNT_BALANCE` / `POSITION` 完整后态 mutation 生成租户隔离的 UPSERT/REMOVE，在同一事务内执行。它按既有业务表精度校验，不接受越界/缺字段并阻止 watermark 前进；未覆盖 posting、funding 去重、保险/ADL 的专属状态，也未做历史回填验收。

后续 Projection 本地提交 `0a8ccfe` 修复回滚失败仍恢复 auto-commit、严重错误漏回滚及 watermark 并发重复消费死锁，并增加 InnoDB/完整唯一键启动门禁。全量 **10 个测试类 / 48 个用例**通过；使用全新依赖目录的真实 MySQL **18 项隔离用例连续 3 轮通过**，包括提交确认丢失后的幂等重试。仅使用合成数据，未部署/重启/注入线上故障，不能据此开启开关或停用 Trade 的 SQL 写入。详细证据和未覆盖范围见 [Projection 事务隔离验收](TRADE_PROJECTION_TRANSACTION_20260929.zh-CN.md)。

已核查：`TradeStateMutation.POSTING` 只是协议常量/恢复器分支，现有 Trade 业务 recorder 未发出该 mutation；普通流水的 ID 还会在 `MySqlDBTradeDao.putPostingBatch` 中生成。故即使余额/持仓/配置物化补齐，仍无法从本地提交日志独立重建资金流水。迁移要先在核心事务确定稳定流水 ID，把完整 posting 与对应余额后态一起提交，并测试重复事件、崩溃窗口和跨账户财务守恒；不能凭 Projection 读取旧 SQL 反向制造权威事件。

CashIn/CashOut 还没有天然稳定的业务去重键：`CashRequest` 本身没有 request ID，`CashResult.request_id` 在当前 `CashInOutFacade` 路径未赋值，`TradeCashStateRecorder` 因此通常只能提交空 requestId。即使补上 POSTING mutation，也不能只凭日志 envelope 随机 eventId 宣称重试不会重复入金/出金；需要在 API 边界引入明确的幂等键和查询/重放契约，并核对已有调用方兼容性。

后续现金/流水候选切片：Trade 本地 `360bda1` / `62615ef` 增加纯事件构造器和 POSTING 恢复预验证，Projection 本地 `dcf26b1` 增加**默认关闭**的 `projection.trade.postingTable.enabled`。候选使用显式客户端操作 ID、稳定流水 ID、请求指纹，将余额后态和完整流水放入同一 STATE_BATCH；旧现金 handler/facade/recorder 未接入，不会因此生成线上 POSTING。真实合成本地日志验证坏流水/未提交状态不安装余额；实际候选构造器的 payload 已通过临时 MySQL 投影验证。Trade 60 类 / 242 用例、Projection 11 类 / 56 用例通过；最终 26 项隔离 MySQL 用例连续 3 轮通过。它不包含请求结果持久去重、现金快照恢复、旧数据迁移、funding/ADL 或 SQL 写入退场，**不能宣布现金 API 已幂等或流水已全量由 Projection 接管**。详见 [现金与流水候选验证](TRADE_CASH_POSTING_CANDIDATE_20260929.zh-CN.md)。

## 发布门禁与顺序

1. 用只读证据确定每个老分区的起点/缺口和业务配置来源：日志、可信本地快照、Order 已提交状态与独立账务记录交叉核对。SQL 只用来比较投影滞后/差异，不能作为自动修复的唯一权威。
2. 对历史缺口制定明确迁移方案并离线演练；尤其要验证订单终态、执行去重、资金余额/流水和所有客户自定义配置。缺口不能证明时保持 NOT_READY，不能反向写库或生成伪空快照。
3. 先让 ProjectionSvr 从已提交 mutation 幂等物化普通余额、持仓和配置业务表，并校验历史回放；然后才分模块迁出 Trade 直接 SQL 写：普通交易/配置/Posting → Funding → 保险与 ADL。每一步要有文件重放、Projection GAP/重启、重复事件/网络分区、失败注入和业务计算一致性测试。
4. 准备全量 A/B 节点容量、复制提交权威来源与只读/Risk 门禁，再按单分区隔离试验和可撤回镜像逐步晋级；压测只在业务与恢复门禁通过后进行。

因此当前部署不变。不能仅凭单节点本地文件存在就宣布安全切主；副本追平、epoch fencing 与已确认提交的来源证明仍是独立门禁。

后续候选增量 `64acf8e`：现金纯计算与预留/提交/安装执行器接到真实协调器的显式候选 hook，查重返回原结果、容量跨分区预留、不确定提交保留容量并撤销 READY，安装后核对完整余额后态再推进索引覆盖。Trade 全量 **295 项**通过，Projection 56 项及隔离 MySQL 27 项一轮复验通过；当前消费者仍拒绝 v2。无自动 bean、无线上入口接线，原 `wdBalance` 的 SQL-first 行为未改；真实 API/admission、全事务覆盖、推送补齐、冷留存/历史账实和 SQL 退场仍是门禁。详见 [候选提交/安装闭环](TRADE_CASH_COMMIT_INSTALL_CANDIDATE_20260929.zh-CN.md)，不将此成绩等同于线上文件权威或异常切主验收。

后续消费者候选 `3122a8d` 已增加默认关闭的现金 v2 校验和原结果查询投影，同事务写入余额/流水/结果/归档/watermark；Projection **73 项**及最终 **45 项×3 轮**隔离验证通过，Trade **295 项**复验通过。新表只属于 Projection 查询面，不能让 Trade 从它恢复或拿它充当历史权威。当前线上未升级/开开关/改表，旧 SQL writer 未退场；实际 schema 迁移、全历史对账、混合覆盖和异常/GAP/重试门禁仍在。详见 [消费者候选验收](TRADE_CASH_V2_PROJECTION_CANDIDATE_20260929.zh-CN.md)。

后续混合覆盖候选 `d934291` 为严格已提交的已知 v1 非现金区间衔接现金原结果覆盖，不能越过未观察旧提交；本地文件恢复可重新证明连续覆盖，未改核心数据来源。新增 25 项后 Trade **320 项**通过，Projection **73 项＋45 项隔离 MySQL 一轮**复验通过。普通成交等真实 adapter 和旧 SQL writer 未改，可信业务后态/历史、全节点冷恢复容量和发布/GAP 仍是门禁；不据原结果索引可恢复宣称线上全业务文件权威完成。详见 [混合交易覆盖候选](TRADE_MIXED_STATE_COVERAGE_CANDIDATE_20260929.zh-CN.md)。

后续整节点候选 `a539940` 先用完整 assignment 清点本机 primary/replica/learner 的本地 snapshot＋committed delta，再合并现金原结果容量，容量不满足不进入首个业务安装；不从数据库加载，也不把未恢复分区算成零历史。新现金门禁默认关闭并在归属/控制面异常时锁闭，精确 snapshot prefix/旧快照隐藏现金及关闭失败拒绝开放；未自动 READY/promotion。最终 **66 类 / 349 项完整两轮**，Projection **73 项＋45 项隔离 MySQL 一轮**通过。无线上接线、历史修改或 SQL writer 退场；最多 256 resident 的停机候选不代表整节点 heap、真实大分区接管、生命周期调度或财务/HA 已验收。详见 [整节点恢复与容量门禁](TRADE_NODE_CASH_CAPACITY_RECOVERY_CANDIDATE_20260929.zh-CN.md)，下一步测隔离大分区资源和恢复时间，再推进实际 adapter/受控异常/TPS。
