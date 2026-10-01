# 租户控制台与自动流动性初始化交接（2026-09-30）

## 系统最终目标与本轮所在位置

OpenTradingCore 的目标不是只交付交易页面或做市机器人，而是提供**业务计算正确、可被租户复用、可扩展且故障后能安全恢复的交易所底座**。近期先把模拟交易和 SaaS 业务链路跑完整；不可因功能演示通过就开放真实资金。完整工作流与安全门禁以[产品与工程交付计划](SAAS_PRODUCT_DELIVERY_PLAN_20260929.zh-CN.md)为准，本交接供下个会话快速定位当前增量。

1. **交易核心正确。** 撮合、成交、手续费、盈亏、保证金、资金费、强平/保险基金/ADL、余额/持仓的业务计算都要由独立预期结果验算；重启、重放、切主后订单和资金状态不得丢失、重复或分叉。MySQL/ClickHouse 是投影，TradeSvr/OrderSvr 以本地持久状态为恢复来源。历史 Web 全链路和 300/16 压测通过不等于当前所有计算场景已完成验收。
2. **API 可独立复用。** Broker API 要足以让租户只凭公开接口搭建交易所；Trade API 要足以编写独立 Robot 策略，包含交易、账户、行情、私有回报、幂等/超时判定、权限与版本化契约。已有双租户 API 回归不能替代外部样板、断线恢复和长稳验收。
3. **集群可扩展、可自动恢复。** Order/Trade/MD 使用可复用底层集群架子，完成跨故障域部署、自动异常检测与安全切换、落后节点追平、在线扩缩容/迁移、epoch fencing 和可观测 RTO/RPO。历史 Order 256/256 READY 与 Trade P000 A↔B 测试证明过特定版本可恢复，不证明无人值守自动恢复或整机故障高可用。同步/异步复制及“副本故障时主节点可配置降级继续接单”是另列需求，不能牺牲已确认订单安全语义。
4. **稳定性和容量有实测口径。** 分阶段压测持续入场、撮合、复制提交、投影可查和客户端端到端 TPS，记录 p50/p95/p99、积压、拒单、OOM、恢复时间及账务差异；做故障注入和长稳。300/16 的历史通过只是小型基线，不是全系统峰值 TPS。
5. **SaaS 可运营。** 申请/审批、租户隔离、默认品种 BTCUSDT、试用做市流动性、租户可热修改参数、移动端/中英文管理界面、平台审批/配额/监控/审计形成完整链路。自动审批条件为申请品种少于 5 个且激活租户少于 200；超过条件进入人工审批。公开开放前必须先完成邮箱激活验证、限流与防滥用。本轮完成了本地 Demo 自动初始化链路，但不能据此宣布整个 SaaS 可公开开放。
6. **真实资金单独禁入。** 不可变复式账本、幂等资金事件、持续对账、钱包/托管与审批、生产级价格源和风控、安全/合规、异地灾备都通过之前，只允许模拟/内部验收资金。自动试用入金绝不能演化成真实资金自动划拨。

## 当前结论

截至 2026-10-01 03:10（Asia/Shanghai），自动审批→独立做市账户→受限 API Key→TradeSvr `cashIn` Demo 入金→`NOTIONAL_ZONES` 策略创建/启用→Robot 核对核心双边订单，已在本地真实跑通。测试申请 `1045ee4e89124289bef5f319d1f3ba54` 对应租户 `XD6PK5`：任务 `COMPLETE/DONE`，入金 10000 Demo、余额 10000，Robot `RUNNING` 且核心查询得到 20 张活动单；做市账号的临时 `enable_cash_in` 已撤销。用户明确接受此测试 Demo 的有限重复入金风险；当前 worker 对结果不明的入金最多重试 3 次，**不能用于真实资金**。

真实交易页浏览器验收随后通过：测试申请 `d747aeb384cf43cfb248d659f14120b9`、租户 `ZS1YUW` 的任务 `COMPLETE` 后，管理员登录显示 BTCUSDT 买 10 档/卖 10 档，示例价量来自盘口而非静态占位；完整截图在测试容器 `/artifacts/trial-liquidity-ZS1YUW.png`。另有一笔 `BH8DF8` 申请在测试 shell 使用保留变量名而提前退出，但审批已成功，自动任务仍完成；不能把它算成浏览器验收。本轮三个 Demo 租户均各注入 10000、各有 20 张 Robot 活动单。匿名 HTTP `MDSvr.queryPublicMarket` 对 `E2E001` 和新租户均返回 9000，虽然实际登录交易页的 WebSocket 行情可见，仍须单独明确这个 HTTP 接口是否应支持匿名调用。MySQL `dc_orders` 为 0 是当前 `projection.saveDemo=false` 的预期行为，不能作为 Demo 核心订单缺失证据；`dc_order_projection_event` 已收到新租户 P050 的事件，Robot 的 20 张来自向交易核心查询后的双边校验。另发现独立的集群问题：ZK P019 标记 `READY`，OrderSvrA 实际持续拒绝 P019 请求（`PARTITION_NOT_READY`、`EPOCH_NOT_ADVANCED`），ProjectionSvr 对 P019 GAP 拉取报 `invalid projection wire magic`。只读 `verify-order-cluster-state-host.sh` 虽报 256/256 PASS，但因没有认证 session 而跳过逐分区 HTTP readiness，故这是一个验收盲区；在修复前不得宣称集群整体健康或继续加压。

## 代码与验证状态

| 部分 | 位置 / 版本 | 当前状态 |
| --- | --- | --- |
| Tenant Web | `dc-saas-tenant-web` 分支 `feat/robot-notional-tenant-console`，`94fa641` 已经 10808 代理推送；本地镜像 `local/dc-saas-tenant-web:sha-94fa641` | 登录与控制台改为交易核心的深色/蓝色风格，菜单改名“流动性管理”，统一主要表格/表单；移动端页面选择器和语言菜单；中文/English 与交易核心共用 `dc-trade-language`；新建做市策略默认选 `NOTIONAL_ZONES`、保证金预算 1000、杠杆 1、档位 `3,3,4`，但默认禁用且不自动创建账户。流动性深层编辑/详情与模板表单的英文已补全。生产构建通过；本地租户 Web 已升级，镜像健康、0 restart、首页资源来自同次完整构建。浏览器模拟 API 的 390px 页面及英文表单校验无溢出/脚本错误；真实登录/CRUD 与自动盘口尚未完成本轮验收。 |
| ManagerSvr | `com.app.dc.managersvr` 分支 `feat/tenant-liquidity-bootstrap`，`5b61afa` 已经 10808 代理推送；本地镜像 `local/dc-saas-managersvr:sha-5b61afa` | `AUTO_APPROVAL` 在审批事务中插入唯一初始化任务，人工审批不入队。Maven 测试通过，容器已升级且 0 restart；新租户申请自动通过、重复 `request_id` 幂等、5 品种申请待审、租户管理员登录均 PASS。 |
| AdminSvr | `com.app.dc.adminsvr` 分支 `feat/admin-unified-20260930`，`ef1e97a` 已经 10808 代理推送；本地镜像 `local/dc-saas-adminsvr:sha-ef1e97a` | 与公开租户目录修复合并在同一源码基线。Maven 全测通过，完整镜像部署且 0 restart，`publicTenantDirectory` code 0。新的 `TrialLiquidityBootstrapWorker` 默认关闭，本地覆盖配置开启后使用数据库租约逐步执行账户/Key/入金/策略/心跳，测试任务已完成。 |
| 数据库迁移 | `mysql/migrations/20260930_tenant_liquidity_bootstrap.sql`；隔离发布分支 `feat/trial-liquidity-bootstrap-deploy` 已经 10808 代理推送 | 本地 MySQL 已执行迁移，任务表 18 列；旧版仅入队表的增量补列和重复执行均通过。记录唯一申请、租约、资金请求 ID、maker ID、Key、入金确认和完成时间；缺表时自动审批不应绕过。主 deploy 工作区仍脏，不可整体推送。 |
| 本地 Demo 启用配置 | `compose.trial-liquidity-local.yaml` | 仅用于本地：worker=true、Demo 歧义重试=true、单次 10000、策略预算 1000；复用已有本地凭据主密钥派生测试账号口令，文件不含密钥值。不可无审查复制到真实资金环境。 |
| Deploy E2E / 计划 | `tests/verify-tenant-auto-approval.py`、`tests/verify-trial-liquidity-browser.js`、`tests/tenant-platform-console-e2e.js`、`tests/verify-robot-tenant-hot-edit.js`、`docs/SAAS_PRODUCT_DELIVERY_PLAN_20260929.zh-CN.md` | 自动审批/API 与真实交易页 10+10 档验收通过。前两个测试脚本随本轮增量加入独立 deploy 发布分支；其余文件有其他会话改动，**不可直接推送整个 `dc-quant-deploy` 本地 `saas-crypto`**。 |

## 下一步必须按顺序完成

1. 先修集群/行情验收缺口：核对 P019 ZK READY 与 OrderSvrA 本地 readiness 分叉、ProjectionSvr GAP 异常；不改动确认订单安全屏障，不用删日志/数据掩盖问题。实际交易页 WebSocket 的 10+10 档已通过，但金额分档计算、移动端可见性仍须细验；查清匿名 HTTP `queryPublicMarket` 9000 是否是通道限制还是回归。
2. 补任务生命周期：租户暂停、试用到期、人工拒绝、配置撤销时自动停用策略并撤销其订单；`COMPLETE` 不能只是一次性成功，需持续健康告警/重入队策略。测试申请仅覆盖 happy path 和一次幂等重放，并发申请、`<200` 门禁、故障注入待测。
3. 为未来**非 Demo/正式**入金接入稳定业务请求 ID 的持久幂等语义，覆盖成功后回包丢失、超时、重启、切主、同 ID 不同金额冲突。当前 live `cashIn` 每请求可加余额；本地 Demo 最多 3 次有界重试的容忍度不可扩大到真实资金。
4. 完成 Broker API 建交易所、Trade API 独立 Robot 策略的外部样板与端到端断线重连测试；再做租户管理热编辑盘口金额、平台管理、邮箱激活与限流安全门禁。
5. `dc-quant-deploy` 本轮迁移、配置样例、交接文档和专用测试已放入隔离分支 `feat/trial-liquidity-bootstrap-deploy`；后续仍须审理本地主分支的大量 ahead commit 与多会话脏文件，不要直接 push `saas-crypto`。Actions 恢复后再统一归位镜像发布链路。

## 发布边界

- 用户选择默认做市使用**模拟资金**，不自动划拨真实资金。具体额度应通过有上限的环境配置决定并记录在任务中，不能直接把 UI 示例预算当成充值金额。
- 邮箱验证仍为公开开放前的安全门禁，目前是待办；内部功能测试不代表可公开放开申请。
- GitHub Actions 要等下个月恢复。本地构建应固定源码 commit、构建完整镜像，并经隔离验收后晋级；不要用单独替换静态文件的方式发布。

## 2026-10-01 P019 故障追因与恢复增量（约 08:00 CST）

本节覆盖上文 03:10 的 P019 未恢复状态；**不是**全 256 分区的新一轮验收。

- 运行中的 Order A/B 镜像源码为 `2d4a305`。P019 的 A/B 快照字节一致：epoch 6、snapshotSeq 717204、committedStateSeq 717201、commitMarkerSeq 717202。A/B 日志尾也一致，末尾 seq 718985；最后累计提交证明为 marker 718982 → state 718976，后面还有未提交的 `STATE_REMOVE`。这些尾部 mutation 不能擅自作为已确认订单恢复。同纪元重启因 `EPOCH_NOT_ADVANCED` 拒绝开放 P019 是正确的安全门禁。
- 重启前 A 对 P019 反复从基线 seq 88961 扫约 62 万条历史，单次由约 56 秒升至 234 秒；出现 append 锁等待和 8–28 秒的批量状态写入。离线日志副本连续调用同一 watermark 对象时，第一次扫描约 4 秒、第二次约 0 毫秒。**冷扫代码根因已定位为并发竞态：`scan()` 在拿缓存锁之前读取 `lastSeq`，另一线程可先推进缓存，前者随后用过期尾序号误判游标倒退并重置到日志基线。**并发回归测试已稳定覆盖这个交错。A 于 02:33:46 重启（exit 0、非 OOM）；重启触发源仍未确认，不能断言由冷扫直接造成。
- 快照边界存在可证实的保守误判：717202 是有效累计 marker，717203–717204 是针对更早 state 的旧 marker；旧代码只允许 `commitMarkerSeq == snapshotSeq`，于是放弃快照快速路径并回扫全部历史。OrderSvr 独立分支 `fix/order-recovery-boundary` 提交 `e674dae` 已经 10808 代理推送：仅在逐条验证短尾全为同纪元旧提交标记时启用快照快路径；任何 mutation/缺口/错误标记仍回退完整验证。另为 Projection 拉取归档段加入 Chronicle 索引 seek。聚焦测试 `OrderCommitWatermarkTest,OrderCommittedRecoveryTest,OrderProjectionCommittedReaderTest` 通过。**新代码尚未部署**；分支基于运行版 `2d4a305`，包含该版尚未合入远端 `saas-crypto` 的性能提交，合并前需审查来源。
- 07:52 对**单个 P019** 用 `tests/promote-fenced-order-partition-host.py` 的快照哈希/ZK CAS 门禁执行 A→B、epoch 6→7；B 记录 `ORDER_PARTITION_UNCOMMITTED_TAIL_ARCHIVED` 与 `ORDER_PARTITION_PROMOTION_READY`，A/B 新快照再次一致。其他 255 分区没有切换。不要直接改 ZK `READY` 或删除未提交尾巴。
- B READY 后 ProjectionSvr 一度仍卡在 `6:718970`：归档拉取每次从头扫描约 62 万条，超过 5 秒 `projection.binary.fetchTimeoutMs`，迟到响应被丢弃。仅本地 override 改为 60000 并重建 **ProjectionSvr 单容器**，使其追赶；约 07:59 MySQL durable order projection watermark 为 `P019 7:728588`，E2E001 `default-depth10` 从 DEGRADED 恢复为 `RUNNING`、20 张活动单、无当前错误码。这个超时是临时缓解；`generate-saas-configs.sh` 仍生成 5000，重新生成配置会覆盖临时值。待归档 seek 代码完成隔离构建/部署验证后，再评估恢复 5000。
- 尚需：部署并验证水位锁顺序修复后 P019/P050 不再冷扫；追查 A 的重启触发源和最后未提交 mutation 的客户端确认/业务对账；补充逐分区带认证的 readiness/route 验证，修复当前 `verify-order-cluster-state-host.sh` 的 256/256 假阳性；对 P019 做订单/资金/投影一致性核对后才算事故关闭。当前不宜直接继续高 TPS 压测。
- 后续只读复查：P019 durable 投影水位继续前进至 `7:733185`，Robot 仍 `RUNNING/20`；`tests/check-projection-consistency-host.sh` 对全局 Order/Trade 事件主键、水位尾、孤儿 mutation 均 PASS。`e674dae` Maven 完整 package 通过，但**未替换运行中的 Order A/B 镜像**。部署此修复前需先证明所有当前 primary 分区没有未提交状态尾，并准备分节点滚动、逐分区本地 readiness、投影追平、业务余额/订单校验；否则不能为了改一段读取逻辑直接重启整节点。
- 08:05 再次在仍运行的 A 上观测到同类冷扫，改为 P050 从 seq 1 反复读约 26 万条；说明这不只属于已故障的 P019。已从 A 实际字节码确认 `computeIfAbsent` 水位缓存和增量 replay 确实存在，排除了“镜像标签新、类文件旧”。提交 `0ad1373` 增加冷扫/重置原因日志；提交 `943b6dd` 将尾序号读取移入缓存锁，并以双线程确定性交错测试确认只解码新增记录，两者已推送至同一 OrderSvr 分支。**修复仍未部署**，所以线上是否消除 P019/P050 的冷扫要待安全滚动后验证。
- 次日继续验证：使用 P019 事发前日志副本和原快照元数据，`943b6dd` 可在约 1.3 秒验证短尾快照边界并算出 committedStateSeq 718976、commitMarkerSeq 718982、lastStateSeq 718985、`uncommittedTail=true`，证明提速没有把未提交状态当成已提交。带认证管理员会话的 `verify-order-cluster-state-host.sh` 真实跑出 256/256 route PASS（255 分区 epoch 6、P019 epoch 7）。验收脚本已改为正式模式自动取得 Demo 管理员会话后逐分区检查；首次初始化无账户时，仅显式 `ORDER_CLUSTER_VERIFY_ALLOW_AUTH_SKIP=true` 允许 assignment/snapshot 预检，并明确输出 PARTIAL，不能再把未扫描路由报作 PASS。另修正 ZK JSON `partitionId` 不在首字段时漏掉 P019 的解析问题。
