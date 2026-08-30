# DC SaaS 加密货币永续合约系统产品与验收说明

文档版本：V1.4

基线日期：2026-08-30

代码分支：`saas-crypto`

当前生产验证环境：`18.140.45.126`，Compose 项目 `dc-saas`；核心隔离回归 `location=POSTFIX2_E2E`，多租户控制面最终回归 `location=SAASA_E2E_0830160159 / SAASB_E2E_0830160159`

## 1. 文档目的与结论

本系统是从既有 DC 通用交易能力中独立演进的 SaaS 加密货币交易系统。它与量化系统的 `latest` 分支相互独立；SaaS 分支不保留量化业务，只复用 GW、公共包、服务发现、订单、交易、行情等成熟基础设施。

截至本基线，单租户单交易对的永续合约核心闭环已经形成并通过自动化验收：登录、测试入金、限价/市价下单、撤单、撮合、行情、订单与成交查询、资金与持仓、手续费、杠杆和风险档位、资金费、只减仓、止盈止损/OCO、部分强平、最终强平、保险基金和事务型 ADL。

本轮在生产验证环境完成峰值档 3,000 个挂单、3,000 个 maker 单、3,000 个 taker 单、并发 32 的严格压力门禁：9,000 个订单请求、6,000 条双方执行记录和 6,000 条成交资金流水全部成功并精确核对，随后重启恢复和平仓归零。五个核心服务共 154 项单元测试全部通过。该轮同时发现并修复 TradeSvr 640 MiB cgroup OOM，以及超时重试未返回首次手续费/PnL 导致 OrderSvr 状态未收敛的问题；失败轮次保留为诊断证据，不计为通过。

2026-08-30 又完成了 SaaS 控制面生产验收：公开试用申请、平台审批、租户初始化、独立 URL、租户内注册、租户管理员、同名用户隔离、品种规则、API Key、流动性 Robot 配置、交易记录、租户设置与审计、暂停和恢复均已形成真实 Web/GW/服务/MySQL 闭环。最终浏览器回归覆盖桌面端和 390×844 手机端。

当前结论是“核心交易功能和第一阶段多租户控制面可供产品验收和继续开发”，不是“可直接承载真实用户资金”。真实资金上线前仍必须完成不可变复式账本/持久化事件、生产指数和标记价、私有流、限流、安全合规、高可用、灾备和更高容量门禁；还需继续对 OrderSvr、TradeSvr、MDSvr、LiqSvr 的全部请求、Topic、缓存、锁和持久化键执行系统性跨租户攻击测试。

## 2. 产品定位与范围

### 2.1 当前产品形态

- 产品类型：USDT 本位加密货币永续合约交易系统。
- 使用方式：Web 交易端经 GW 调用后端服务；业务服务仍可供 API/策略调用。
- 租户标识：当前以 `location` 区分租户。
- 事务数据库：MySQL。
- 行情/K 线数据库：ClickHouse。
- 服务发现：ZooKeeper。
- 部署方式：公开容器镜像、Docker Compose 一键部署/卸载、定时自动更新和失败回滚。
- 当前验收品种：`BTCUSDT`，市场标识 `4`。

### 2.2 当前不包含的范围

- 真实链上充值、提现、归集和冷热钱包；页面 Deposit 仅为测试记账。
- KYC/KYB、AML、制裁筛查、Travel Rule 和司法辖区合规。
- 生产级多活、多可用区和撮合热备。
- 完整 Binance/Bybit 协议兼容层与官方 SDK 兼容承诺。
- 自定义域名自动解析、证书自动签发、套餐计费、完整平台 RBAC、KYC 和租户配额计费；当前已交付 location 独立 URL 与第一阶段平台/租户管理控制台。
- RobotSvr 的正式生产验收；实现、镜像构建、数据库迁移和一键部署编排已完成，但在 RobotSvr GHCR 包切换为 Public 前仍不计入当前生产验证环境 13 个核心容器。

## 3. 用户入口与当前账号

- Web 地址：`http://18.140.45.126:18088/#/login?location=POSTFIX2_E2E`
- 验收用户：`p2buyer` 或 `p2seller`
- 密码：使用部署时由运维设置的验收密码；文档不保存明文凭据。
- 页面使用 HTTP，浏览器显示“不安全”是测试环境预期；生产必须启用 HTTPS、HSTS 和可信域名证书。

### 3.1 专业交易工作区

交易端采用专业 USDT 永续合约工作区，保留本系统现有业务字段和服务接口：

- K 线图、订单簿/最近成交、下单、持仓/委托/成交和账户资产共五类面板。
- 桌面端支持拖动、缩放和自动重排；可以锁定布局防止交易时误操作，也可以一键恢复默认布局。
- 布局按 `location + user_id` 保存在浏览器本地，刷新后恢复，不同租户和用户互不共享。
- 支持中文和英文切换；行情、下单、表头、方向、订单类型和状态随语言变化，协议标识保持原值。
- 顶部行情条突出展示最新成交价，并按涨跌方向着色；下单区在请求发出前校验数量、限价和触发价必须为正数。
- 市场抽屉支持中英文搜索和空结果提示；选择品种时直接使用服务数据中的交易对代码，不依赖 DOM 文本反解析。
- 切换品种和离开交易页时统一释放订单、成交、持仓、资金、订单簿和行情 WebSocket 订阅，防止重复回报与无效取消订阅异常。
- 使用深色层级、专业买卖色、紧凑表格和响应式断点，功能布局参考主流永续合约交易终端，但不复制其品牌和专有素材。

Web 源码当前部署基线为 `97b3afe88928fe0c6b26a8564d88ae5168556dba`，运行不可变公开镜像 `source-97b3afe88928fe0c6b26a8564d88ae5168556dba`。生产环境已完成真实浏览器桌面英文/中文、390×844 手机英文/中文、拖动、缩放、布局持久化、市场抽屉、完整交易链路、租户申请/注册和平台/租户管理验收；本报告中的 Web 图片均来自 `18.140.45.126`，不是本地效果图。

## 4. 总体架构与服务职责

```text
Web / API / RobotSvr
          |
          v
        GW ---- LoginSvr（登录、会话）
          |
          +---- OrderSvr（规则校验、幂等、订单簿、撮合、条件单）
          |          |                  |
          |          | execution        +---- MDSvr（租户订单簿/逐笔/K线）
          |          v                               |
          +---- TradeSvr（余额、持仓、保证金、费用、资金费、保险、ADL）
          |          ^                               v
          |          | position/mark               ClickHouse
          +---- LiqSvr（强平监控、部分/最终强平）
          |
          +---- APSSvr（指数行情中心；外部行情 -> 指数/标记价输入）
          |
          +---- AdminSvr（面向 Web 的管理接口）
          +---- ManagerSvr（后台运营管理）

Order/Trade/Login/Admin/Manager/Liq 事务与配置 -> MySQL
全部服务发现与路由 -> ZooKeeper
```

| 服务 | 当前职责 | 关键租户边界 |
|---|---|---|
| GW | HTTP/WebSocket 入口、服务路由、Topic 转发 | 当前保持通用网关；不在本阶段强改。服务 snapshot 校验订阅，校验失败不返回订阅确认，GW 不把 Topic 加入订阅表 |
| LoginSvr | 用户注册、登录、会话、租户生命周期校验和 API Key | 用户凭据与 location 绑定；错误 location、暂停租户、错误密码已验收拒绝 |
| OrderSvr | 参数、品种和订单规则；幂等；改单/撤单；价格时间优先撮合；条件单 | 订单簿、锁、幂等和撮合序列包含 location、market、symbol |
| TradeSvr | 账户余额、冻结、持仓、保证金、手续费、资金费、保险基金、ADL | 余额/持仓/流水/ADL 查询和写入包含 location |
| LiqSvr | 消费租户标记价格与持仓，触发部分或最终强平 | 标记价 key、重试 key、强平订单均包含 location |
| MDSvr | 每个租户独立订单簿行情、最近成交和 K 线 | 行情不是全租户共享；按 location 发布和持久化 |
| APSSvr | 外部行情接入、指数计算输入、向 GW/MDSvr 提供指数类行情 | 当前生产验证单一 Binance Futures 外部源；后续按租户指数方案配置多源计算 |
| AdminSvr | 面向 Web 的租户管理接口：用户、品种、API Key、Robot、交易记录、设置和审计 | location 取自认证会话；跨 location 和非管理员访问已验收拒绝 |
| ManagerSvr | 平台运营：申请、审批、初始化、生命周期、独立 URL | 仅 PLATFORM 角色可审批和变更租户；操作写审计 |
| RobotSvr | 租户策略/流动性服务：订阅 APSSvr 的 Binance Futures 10 档深度，使用租户 API Key 向 OrderSvr 提交 PostOnly 报价；价差内用户挂单由 IOC 扫单；内部成交后按净持仓差额经 APSSvr 反向对冲 | 所有配置、订单查询、持仓、扫单和对冲流水均绑定 location + robot + symbol；外部凭据只以环境变量别名注入；代码与本地测试完成，生产容器和真实币安账户对冲待验收 |

## 5. 核心交易业务规则

### 5.1 订单身份与生命周期

- 租户内订单身份由 `location + user_id + ClOrdID` 约束。
- 相同 ClOrdID、相同订单指纹的重试返回既有结果，不重复下单。
- 相同 ClOrdID 但价格、数量、方向、订单类型、只减仓或触发参数不同，按幂等冲突拒绝。
- 状态覆盖 `Newing`、`New`、`Partially_Filled`、`Filled`、`Pending_Cancel`、`Cancelled`、`Rejected`、`Expired`、`Untriggered`、`Triggered`。
- 同一 `location + orderId` 的订单生命周期事件串行处理。订单已进入终态后，迟到的 Newing 不得重新冻结资金。
- OrderSvr 访问 TradeSvr 超时时按“不确定结果”重试，不伪造 Rejected；压力测试会把任何异步 Rejected 视为失败。

### 5.2 品种过滤器

每个交易品种从配置读取并校验：

- 交易开关和过期状态。
- `tick_size`：限价必须为价格步长整数倍。
- `qty_tick_size`：数量必须为数量步长整数倍。
- `min_order_qty`、`max_order_qty`。
- `min_notional`：限价名义金额 `price × quantity` 不得低于门槛。
- `max_price`。
- `market_take_bound`：市价单从最优对手价计算保护限价，买单向上、卖单向下限制最大吃单范围，并按 tick 对齐。

当前 BTCUSDT 验收配置使用 0.1 价格步长、0.0001 数量步长、0.0001 最小数量、10 最大数量、5 USDT 最小名义金额、5% 市价保护边界和 1,000,000 最大价格。

### 5.3 订单类型与 TIF

| 能力 | 当前规则 |
|---|---|
| Limit + GTC | 未成交数量按价格时间优先进入订单簿 |
| Limit + IOC | 立即成交可成交数量，剩余数量取消，不挂入订单簿 |
| Limit + FOK | 下单前预检全部可成交数量；不能全部成交则整单不成交 |
| Post Only / PO | 只允许 Limit；若立即成为 taker 则拒绝/取消，保证 maker 语义 |
| Market | 必须使用 IOC；订单簿为空时取消；使用最优对手价与 market_take_bound 生成保护限价 |
| 条件限价/市价 | 支持 Trigger、Stop、StopMarket、TakeProfit、TakeProfitMarket 等触发入口 |

### 5.4 撮合规则

- 每个 `location + marketIndicator + securityID` 是独立订单簿。
- 买方最高价优先、卖方最低价优先；同价按进入撮合序列的时间优先。
- 每个订单簿所有被接受的新订单进入单写撮合序列，避免并发下出现残留交叉盘口。
- 成交价采用簿内 maker 价格；双方分别生成执行记录，明确 maker/taker 标记和费率。
- GTC 未成交余量可挂单；IOC/FOK/Market 不保留余量。
- 撮合后的订单簿必须满足最高买价小于最低卖价；压力测试对此做硬断言。

### 5.5 自成交保护（STP/SMP）

- 自成交身份至少要求相同 location 和相同用户；跨租户或不同用户不视为自成交。
- 已实现 `CANCEL_TAKER`、`CANCEL_MAKER`、`CANCEL_BOTH` 三种模式解析和撮合行为。
- 未传或传入非法模式时 fail-safe 为 `CANCEL_TAKER`。
- 当前主机级严格验收覆盖默认 Cancel Taker；SMP group、租户级组合规则和三模式完整接口验收仍属于后续产品化门禁。

### 5.6 撤单、改单和批量操作

- 普通撤单必须匹配 location、用户和订单身份。
- Replace 为原子取消并重建；关键身份、方向和只减仓语义必须一致，失败不能留下半完成状态。
- Batch Cancel 只能取消当前 location 和当前用户的指定订单。
- Mass Cancel 按用户、location、市场/品种边界清理活动单。
- 撤单或终态后冻结保证金和冻结手续费不得小于 0，最终必须完全释放。

### 5.7 只减仓、平仓与保护订单

- `reduceOnly=true` 只能用于 `OCType=ClOSE`；开仓单设置 reduceOnly 直接拒绝。
- reduceOnly 单不得同时新建 TP/SL，避免平仓订单再次派生保护单。
- 平仓数量不能超过对应方向可用持仓；成交后不得反向开仓。
- Web Close 生成反向 Market/IOC/ReduceOnly 平仓单。
- 开仓订单可附带 StopLossPrice 和 TakeProfitPrice；保护单继承 location、用户、品种和原始引用，触发后仍为 reduce-only Close。
- 同一父单的止盈/止损构成 OCO；一侧触发后取消另一侧。
- 追踪止损枚举已存在，但未完成生产级回调率、激活价和接口验收，因此不作为当前已交付能力。

## 6. 资金、持仓与风险规则

### 6.1 账户字段

- `balance`：已结算账户余额。
- `used_margin`：持仓占用保证金。
- `freezed_margin`：活动开仓委托冻结保证金。
- `freezed_commission`：活动委托冻结手续费。
- 持仓按 long/short 分别记录数量、均价、占用保证金、锁定数量和强平价。

### 6.2 杠杆与风险档位

- 用户可按 `location + user + symbol` 配置杠杆，当前允许范围 1–100。
- 风险档位按名义价值递增配置 notional floor/cap、维持保证金率、维持保证金扣减额和最大杠杆。
- 更高档位的维持保证金率不得下降，最大杠杆不得上升。
- 新开仓使用 `max(markPrice, orderPrice) × projectedQuantity` 检查名义价值和档位最大杠杆。
- 超过最后一个风险档位上限或杠杆超过当前档位上限时拒绝。

### 6.3 保证金和手续费

- 初始保证金基础值：`positionNotional / leverage`。
- 多仓破产价：`entryPrice × (leverage - 1) / leverage`。
- 空仓破产价：`entryPrice × (leverage + 1) / leverage`。
- 为防止开仓后无法承担平仓费，剩余整个持仓按破产价预留 taker 平仓手续费；maker 开仓优惠不得降低该保守预留。
- 实际成交手续费：`lastQty × lastPx × makerOrTakerRate`，扣款以负资金流水记录。
- 部分平仓按成交数量计算已实现盈亏，按剩余持仓重算均价、保证金和保守平仓费预留。
- 单向翻仓时先完整关闭原方向，再按剩余数量建立新方向；手续费始终按实际 maker/taker 方向扣减，不得倒记为收入。

### 6.4 资金流水持久化

- 成交、入金、资金费、ADL 实现盈亏和 ADL 分摊均生成带 location、用户、品种、来源、来源 ID 和时间的资金流水。
- 普通成交流水在 TradeSvr 请求线程外批量写 MySQL；单批最多 250 条，失败整批原样重试。
- Docker 优雅停止时等待流水队列排空；本轮 3,000/32 压力下 6,000 条成交流水在重启前精确落库。
- 当前队列仍是进程内队列，不是持久化 outbox。宿主机断电、SIGKILL 或长时间 MySQL 不可用仍可能导致未落库数据丢失；真实资金前必须改为事务 outbox/不可变账本。

### 6.5 资金费

- 结算周期必须为 1–24 小时的整小时数。
- 每个品种按调度时间扫描全部 location 的持仓，并从对应租户标记价和资金费率计算。
- 净持仓：`longPosition - shortPosition`。
- 余额变化：`-netPosition × markPrice × fundingRate`，保留 8 位小数。
- `(location,user,symbol,settlementTime)` 使用唯一结算记录；重复调度、重放或重启不得重复扣款。
- 结算记录、余额、持仓保证金调整和资金流水在同一 MySQL 事务内完成。

## 7. 强平、保险基金与 ADL

### 7.1 强平触发

- LiqSvr 消费按 location 发布的标记价格和 TradeSvr 持仓。
- 多仓：`markPrice <= longLiqPrice` 触发。
- 空仓：`markPrice >= shortLiqPrice` 触发。
- 重试 key 包含 location、用户、品种和方向；默认重试窗口内禁止重复发起。
- 发强平单前先尝试取消该用户活动单并释放冻结资产。

### 7.2 部分与最终强平

- 默认部分强平比例 25%，数量向上/向下按品种 step 对齐，并保证剩余仓位仍能满足最小数量。
- 无法形成合法部分数量时直接最终强平。
- 强平订单固定为反向 `ClOSE + ReduceOnly + Market + IOC`。
- 部分强平标记 `close_by=liq_partial`；最终强平标记 `close_by=liq`。
- 只有实际撮合成交后，TradeSvr 才更新余额、持仓和亏空；不会仅凭“已发强平请求”宣称完成。

### 7.3 保险基金

- 最终强平后的负余额/穿仓差额首先由 `location + securityID` 的保险基金覆盖。
- 保险覆盖额不超过基金可用余额。
- 亏空、已覆盖、未覆盖、ADL 已覆盖和剩余金额写入 `dc_liquidation_deficit`。

### 7.4 ADL 候选与排序

- 只在相同 location、相同品种中选择与被强平方向相反的盈利持仓。
- 多头盈利单价：`referencePrice - averagePrice`；空头盈利单价：`averagePrice - referencePrice`；非盈利候选排除。
- 盈利率：`unrealizedProfit / usedMargin`。
- 有效杠杆：`positionNotional / (accountBalance + unrealizedProfit)`。
- 排名分数：`profitRate × effectiveLeverage`，按分数、盈利率、有效杠杆降序，再按 userID 稳定排序。
- 按排名依次减仓；减仓数量按品种 step 对齐，不超过候选可用持仓。
- 单候选事务同时更新候选持仓、持仓保证金、账户余额、`ADL_REALIZED`、`ADL_ALLOCATION` 和 ADL ledger。
- 全部候选、保险基金、被强平账户、亏空事件和 ADL 状态在一个 MySQL 事务内提交；并发变化导致受影响行数不符时回滚。
- 当前支持 `COMPLETED` 和仍有剩余亏空的部分覆盖状态，不会把未覆盖亏空伪装为完成。

## 8. 行情规则与数据流

### 8.1 租户行情不是共享订单簿

用户已明确要求每个租户有独立订单簿，因此 MDSvr 的深度、最近成交和 K 线必须带 location。两个租户即使使用相同 `BTCUSDT`，订单簿和成交也不能合并。

### 8.2 当前数据流

```text
外部交易所行情 -> APSSvr -> 指数/参考行情 -> MDSvr / GW
OrderSvr 订单簿变更 -> MDSvr -> location 维度 depth/ticker
OrderSvr 成交 -> MDSvr -> location 维度 recent trade / Kline
MDSvr -> ClickHouse dc.kline(location, securityID, type, startTime, ...)
MDSvr snapshot -> 服务端校验 location/topic -> GW 仅登记已确认订阅
```

- 当前 ClickHouse `dc.kline` 已包含 location，验收中同一个逻辑键能按 `CORE_E2E` 和 `WEB_E2E` 独立保存。
- GW 保持通用转发角色。订阅权限由提供 snapshot 的业务服务校验；校验失败时不返回订阅确认，GW 不加入订阅 Topic，后续广播不会发给该连接。
- 后续仍需为 depth delta 增加序号、断线快照恢复、乱序检测和可复算的一致性协议。

### 8.3 当前环境行情状态

生产验证环境的 APSSvr 已能持续接收 Binance Futures ticker/bookTicker，并向 MDSvr/GW 发布。Web 自动化同时验证订单簿、最近成交、K 线持久化、Last/Mark/Index 展示；外部单一数据源可用不等于生产指数方案完成，真实资金上线仍需多源加权、中位数/异常值剔除、断源降级和偏离保护。

上线门禁：至少三个独立来源、来源权重、时间戳新鲜度、异常值剔除、中位数/加权指数、断流降级、标记价平滑、价格保护、监控和审计全部通过后，才允许真实资金交易。

### 8.4 Robot 流动性与外部对冲规则（实现完成、生产待验收）

- APSSvr 订阅 Binance Futures 100 ms partial-depth 10 档并发布 `dc.aps.depth.BNFutures.<symbol>`；RobotSvr 只消费该行情，不绕过 APSSvr 直连行情。
- 一个 Robot worker 固定绑定 `location + robot_id + security_id + tenant API key`。默认上下各 10 档，价格跟随 Binance 档位，数量使用租户固定值或外部数量缩放值，并继续受 tick、step、最小数量、最小名义金额、单档上限和库存上限约束。
- 常规报价为 PostOnly，避免 Robot 主动成为 taker。部分成交后按剩余数量而不是原始数量对账，撤旧补新恢复完整档位。行情超时、价格瞬时偏离、连续运行异常、配置停用、服务退出或未决外部对冲都会撤销 Robot 活动单并停止继续报价。
- 用户卖单严格进入外部卖一以内，Robot 才以 Buy IOC 扫单；用户买单严格进入外部买一以内，Robot 才以 Sell IOC 扫单。扫单受最大允许损失 bps、单次最大数量和库存上限约束。外部买一/卖一同价边界不扫，避免 IOC 先打到 Robot 自己的镜像订单。
- Robot 报价或扫单成交后，以“目标外部仓位 = 租户内 Robot 净持仓的相反数”计算差额，通过 APSSvr 向 Binance Futures 报 Market 对冲单。
- 外部对冲在发送前先事务写入 `dc_robot_hedge_execution`，使用确定性 clientOrderId。响应不确定时立即停报，并用同一 clientOrderId 查询 Binance；完全成交、部分终态、失败终态分别落 FILLED、PARTIAL、FAILED，未知状态持续阻断，防止重复全量对冲。
- Binance API Key/Secret 不写数据库、不返回 Web，只允许在 RobotSvr 容器的 `ROBOT_HEDGE_ACCOUNTS_JSON` 中按 `hedge_account_ref` 解析。

## 9. 端到端数据流向

### 9.1 登录

1. 浏览器 URL 携带 location，向 GW 发送 LoginSvr 登录请求。
2. LoginSvr 按用户和 location 校验凭据。
3. 成功后建立会话并加载用户信息；错误 location 返回认证失败。
4. 当前仍需后续把会话中的服务端权威 location 注入所有业务调用，彻底忽略客户端伪造值。

### 9.2 下单与成交

1. Web/API -> GW -> OrderSvr `placeOrder`。
2. OrderSvr 校验基础字段、品种过滤器、TIF、reduceOnly、幂等和用户身份。
3. OrderSvr -> TradeSvr 预冻结保证金/手续费并检查风险档位。
4. 接受的订单进入 `location + market + symbol` 单写撮合序列。
5. 撮合按价格时间优先生成 maker/taker 两方 ExecOrder；未成交余量按 TIF 挂单或取消。
6. ExecOrder -> TradeSvr：扣费、更新余额/持仓/保证金、生成流水并持久化。
7. 订单/执行 -> MDSvr：生成独立租户盘口、最近成交和 K 线。
8. OrderSvr/TradeSvr/MDSvr -> GW Topic -> Web：刷新委托、成交、持仓、资金和行情。

### 9.3 撤单

1. Web/API -> GW -> OrderSvr cancel/batch/mass cancel。
2. OrderSvr 在订单身份边界内将活动单转为 PendingCancel/Cancelled 并移出订单簿。
3. 撤单事件 -> TradeSvr 释放冻结保证金和手续费。
4. 即使取消事件先于迟到 Newing 到达，TradeSvr 也以终态为准，不再二次冻结。

### 9.4 强平与 ADL

1. APSSvr/MDSvr -> LiqSvr：按 location 提供标记价。
2. TradeSvr -> LiqSvr：提供同 location 持仓快照。
3. LiqSvr 比较标记价和强平价，取消活动单并向 OrderSvr 发部分/最终强平单。
4. OrderSvr 实际撮合；ExecOrder 回到 TradeSvr。
5. TradeSvr 结算已实现盈亏、费用和剩余保证金。
6. 最终负余额先扣租户保险基金，再筛选同租户反向盈利持仓并执行 ADL。
7. MySQL 事务提交 deficit/event/ledger/posting/balance/position；GW 向相关用户发布更新。

## 10. 多租户控制面

第一阶段多租户控制面已经落地并完成生产双租户验收，分为平台端、租户端和交易端三层。`location` 是租户唯一边界；GW 保持通用路由和 Topic 转发能力，认证、管理和各业务服务负责校验自身请求与 snapshot。

### 10.1 试用申请与审批

- 公开页面提交企业/团队、租户代码、联系人、用途、预计用户数、交易品种和试用周期；申请 ID 可用于查询状态。
- ManagerSvr 平台运营审批或拒绝申请，重复请求凭证不会重复创建租户。
- 审批通过后事务内创建 location、租户管理员、默认账户/配置、品种规则、试用期限和独立 URL。
- 当前独立 URL 使用 `/#/login?location={LOCATION}`；自定义域名、自动 DNS 和证书属于下一阶段。
- 生命周期覆盖 `TRIAL / ACTIVE / SUSPENDED / EXPIRED`。暂停或到期后注册、普通用户登录和交易入口被拒绝；历史数据与审计保留，恢复 ACTIVE 后重新开放。

### 10.2 租户管理员

- 用户：租户内注册、管理员创建、启停和重置初始密码；同一用户名可在不同租户独立存在。
- 品种：交易状态、精度、最小/最大数量、最小名义金额、价格上限、手续费、资金费周期和风险档位。
- API Key：创建、列出和撤销；Secret 只在创建时显示一次。
- Robot：报价档位、价差、数量、库存上限、外部对冲配置、启停和熔断参数的控制面。
- 交易：按本租户查询订单、成交和相关交易记录。
- 设置：注册/交易开关、默认语言和品牌参数。
- 审计：用户、品种、API Key、Robot 和设置变更留痕；资金人工调账审批、2FA、角色细分和导出审批仍属后续。

### 10.3 平台管理员

- 已交付申请审批、租户初始化、试用到期、注册/交易开关、状态切换、location URL 和审计。
- 平台运营使用独立 `PLATFORM` 账号；普通租户管理员和交易用户无审批权限。
- 套餐计费、配额、独立域名、跨租户健康容量视图、灰度发布和平台角色细分仍属后续。

### 10.4 location 强制边界实施原则

- 用户已决定暂不直接改 GW；先由每个业务服务完成 snapshot/请求身份校验，同时设计 GW 的可选租户插件，保证通用 GW 仍可用于非多租户系统。
- LoginSvr 登录会话产生权威 location；AdminSvr 和 ManagerSvr 已使用认证上下文并拒绝越权 location。后续如启用可选 SaaS GW 插件，GW 可注入并拒绝冲突字段；未启用时保持普通透传。
- MySQL 主键、唯一键、索引、RocksDB key、缓存 key、锁 key、Topic、幂等键和导出路径全部包含 location。
- 任何跨 location 的查询、撮合、撤单、订阅、Robot 报单和管理操作必须默认拒绝，并产生安全审计。

## 11. 生产验证环境部署与运维

### 11.1 当前核心容器

核心 13 个容器：MySQL、ClickHouse、ZooKeeper、GW、LoginSvr、MDSvr、APSSvr、OrderSvr、TradeSvr、LiqSvr、ManagerSvr、AdminSvr、Trade Web。Playwright runner 是验收辅助容器，不计入核心 13 个。

### 11.2 内存限制

| 服务 | JVM Xmx | 容器上限 |
|---|---:|---:|
| GW、LoginSvr、LiqSvr、ManagerSvr、AdminSvr | 256 MiB | 384 MiB |
| MDSvr、APSSvr、OrderSvr | 448 MiB | 640 MiB |
| TradeSvr | 384 MiB | 896 MiB |
| MySQL | - | 1.5 GiB |
| ClickHouse | - | 2 GiB |
| ZooKeeper | - | 384 MiB |
| Trade Web | - | 256 MiB |

最终检查所有核心容器 running，RestartCount=0，OOMKilled=false。

### 11.3 自动更新

- SaaS 部署目录为 `/home/ec2-user/dc-saas-deploy`，运行数据为 `/data/dc-saas-runtime`；与同机量化 Compose 项目和数据目录分离。
- root cron 已安装为每 5 分钟执行 `/home/ec2-user/dc-saas-deploy/auto-update-saas.sh`，只管理 Compose 项目 `dc-saas`，日志位于 `/data/dc-saas-runtime/log/auto-update-saas.log`。
- 只从公开 GHCR 拉取应用镜像，不自动更新 MySQL、ClickHouse、ZooKeeper。
- 新镜像需要稳定窗口后成组部署；失败自动恢复上一组镜像。
- 验收报告记录每个运行容器的不可变 image ID；自动更新以整组远端 digest 指纹和稳定窗口判定发布，测试过程中不允许版本漂移。
- Web 固定为 `source-97b3afe88928fe0c6b26a8564d88ae5168556dba`；自动更新只替换发生不可变镜像变更的服务，本轮 Web 更新未重启核心交易服务。
- GitHub 网络偶发 reset/timeout 时，当前运行服务保持不变；源码提交使用直连官方地址重试，不允许 Git 网络问题阻塞开发。

## 12. 测试与验收结果

### 12.1 源码测试

| 服务 | 测试数 | 失败 | 错误 |
|---|---:|---:|---:|
| OrderSvr | 49 | 0 | 0 |
| TradeSvr | 62 | 0 | 0 |
| LiqSvr | 11 | 0 | 0 |
| MDSvr | 12 | 0 | 0 |
| APSSvr | 20 | 0 | 0 |
| AdminSvr | 13 | 0 | 0 |
| ManagerSvr | 7 | 0 | 0 |
| LoginSvr | 5 | 0 | 0 |
| RobotSvr | 18 | 0 | 0 |
| 合计 | 197 | 0 | 0 |

Trade Web 同期执行 `npm run build-prod` 成功；AdminSvr、ManagerSvr、LoginSvr 使用受控小内存 Maven 参数完整运行测试，未通过跳过测试生成镜像。

### 12.2 压力与稳定性

| 轮次 | 并发 | 订单请求 | 执行记录 | 成交流水 | 结果 | 关键性能 |
|---|---:|---:|---:|---:|---|---|
| POSTBATCH200 | 4 | 600 | 400 | 400 | PASS | 三阶段约 19.3/19.5/17.6 req/s |
| PROD-1000×16 | 16 | 3,000 | 2,000 | 2,000 | PASS | 挂单/maker/taker 81.6/144.9/146.8 req/s；p99 814/206/326 ms |
| PROD-3000×32 | 32 | 9,000 | 6,000 | 6,000 | PASS | 挂单/maker/taker 143.9/214.5/232.6 req/s；p99 803/311/310 ms；最大 1.60 s |
| STABILITY R1 | 8 | 1,500 | 1,000 | 1,000 | PASS | 含状态服务重启恢复与平仓归零 |
| STABILITY R2 | 8 | 1,500 | 1,000 | 1,000 | PASS | 含状态服务重启恢复与平仓归零 |
| STABILITY R3 | 8 | 1,500 | 1,000 | 1,000 | PASS | 含状态服务重启恢复与平仓归零 |
| 合计 | - | 17,100 | 11,400 | 11,400 | PASS | 无异步拒单、无重复记录、无交叉盘口、无 OOM |

每一轮不仅检查 HTTP 成功，还等待并精确核对订单、双方 execution、双方 posting、手续费汇总、余额、持仓、保证金、撤单、订单簿唯一性；随后重启 OrderSvr/TradeSvr，验证恢复一致，再用 reduce-only 对敲平仓并验证占用归零。

生产高压先后执行了两类失败注入式诊断：原 640 MiB TradeSvr 在约第 1,960 笔 taker 成交时被 cgroup OOM；增加受控堆外余量后，首次 3000×32 得到订单 9000/9000、流水 6000/6000，但 OrderSvr 成交回报仅 5229/6000。根因分别修复为 896 MiB 容器上限/原生内存约束/成功路径降噪，以及 TradeSvr 幂等重试返回首次完整 PResult。最终独立 location 重跑达到 9000/6000/6000、0 重启、0 OOM。失败结果与修复后结果均保留日志，避免只报告成功轮次。

### 12.3 完整业务验收

- 13 个核心容器、40 张 MySQL 表、26 个 location 字段和 Web 健康：PASS。
- MySQL/ClickHouse 双 location 隔离：PASS。
- tick/step/minNotional、GTC/IOC/FOK/PostOnly/FIFO/STP：PASS。
- ClOrdID 幂等冲突、Replace、Batch Cancel、Mass Cancel：PASS。
- 双浏览器登录、测试入金、挂单、撤单、成交、最近成交、市价平仓、历史与资金：PASS。
- 部分强平：PASS。
- 最终强平、1 USDT 保险覆盖、2.0036 USDT ADL、数量步长对齐：PASS。
- 多候选 ADL 按盈利率和有效杠杆排序、跨 location 不变：PASS。
- 完整验收日志：`/data/dc-saas-runtime/e2e-artifacts/core-full-acceptance-postfix.log`；3000×32 日志：`core-stress-3000x32-retry.log`，退出码 0。

### 12.4 多租户控制面生产验收

最终自动化在公开 Web/GW、真实 ManagerSvr、AdminSvr、LoginSvr 和 MySQL 上创建两套独立租户 `SAASA_E2E_0830160159` 与 `SAASB_E2E_0830160159`，完成以下断言：

- 公开申请、状态查询、PLATFORM 审批、location/独立 URL 和租户管理员初始化：PASS。
- 同一用户名在两个 location 注册得到不同 user_id；错租户密码和错误 location 登录：拒绝。
- 普通用户调用平台审批、交易用户调用租户管理、A 租户管理员访问 B 租户数据：拒绝。
- 租户管理员创建用户、品种查询与 UPSERT、交易记录、设置和审计：PASS。
- 租户暂停后登录受阻，恢复 ACTIVE 后重新登录：PASS。
- 桌面申请页、桌面平台运营页、桌面租户管理页、390×844 注册页和租户管理页：真实浏览器 PASS。
- 测试产物：`/data/dc-saas-runtime/e2e-artifacts/tenant-0830160159`。证据租户按审计要求保留，未执行未经授权的数据删除。

自动化曾在真实 MySQL 暴露历史 `dc_symbol` 数字列包含空字符串，审批复制到 DECIMAL 失败；ManagerSvr 与 AdminSvr 已统一通过 `TRIM / NULLIF / CAST` 规范化旧规则。部署预检还发现运行中主机不应按 8 GiB 可用内存拒绝增量更新，现已拆分总内存 7.5 GiB 与可用内存 2 GiB 门禁。修复后重新构建公开镜像并完成全链路回归。

## 13. 截图证据

### 13.1 生产环境桌面交易工作区

![生产环境英文桌面交易工作区](evidence/workspace-en.png)

![生产环境中文桌面交易工作区](evidence/workspace-zh.png)

### 13.2 生产环境完整 Web 交易链路

![Web 交易界面、最近成交、账户资金和下单区域](evidence/buyer-trading-flow.png)

![第二用户成交历史与账户状态](evidence/seller-trade-history.png)

![订单簿、最近成交、K 线和 Last/Mark/Index 行情](evidence/web-market-data.png)

### 13.3 生产环境手机交易工作区

![390×844 英文手机交易工作区](evidence/workspace-mobile-en.png)

![390×844 中文手机交易工作区](evidence/workspace-mobile-zh.png)

### 13.4 MySQL、ClickHouse 与容器证据（生产环境）

![真实数据库查询与运行镜像证据](evidence/database-evidence.png)

### 13.5 多租户申请、注册与管理证据（生产环境）

![公开 SaaS 试用申请](evidence/tenant-application-en.png)

![390×844 租户内注册](evidence/tenant-registration-mobile-en.png)

![平台租户运营与生命周期](evidence/platform-tenant-operations-en.png)

![租户管理员桌面控制台](evidence/tenant-administration-en.png)

![390×844 租户管理员控制台](evidence/tenant-administration-mobile-en.png)

证据 SHA-256：

- `buyer-trading-flow.png`：`19712c9c9c23982daa26f75d0ba66246227e0492b91dd278c549d1d2e9137a7d`
- `seller-trade-history.png`：`33035bf00a3835e25da14bcc5c9f8fa617093637941b52cac32ffa21f4147ecc`
- `web-market-data.png`：`130c8669ce9badbfe8dec6c53e7b55fa6ec2adcb10234dbdc0b7d921f6b2155e`
- `workspace-en.png`：`7891a7b143caed914b358a7350eef32c7273ba29cdf490f27263503059b00667`
- `workspace-zh.png`：`88b1c9c926e86b2837b862cc2a525a1d29e1984e79ddefe696103300055b906d`
- `workspace-mobile-en.png`：`ded9008f1509462f02820a7e6d10c87263f3c599c5f597e151736bd56705a693`
- `workspace-mobile-zh.png`：`b3978c5a7dc17c8222c8d37b0c5b850b67a1707f0aa562f8ace0e85196471cf1`
- `database-evidence.png`：`13ae3ced4d100e095d751b8a295468964d4c2da8224097affa6ba2bfe1e7d267`
- `tenant-application-en.png`：`a0661d1cf673862fe7369274fa664b3d5905f410d00b239e1f53fb7a56e9abb7`
- `tenant-registration-mobile-en.png`：`f66a33ba34fab0fd3203381daefe00af8f073d7c24e599d7986174482e15071d`
- `platform-tenant-operations-en.png`：`1b72269c80aa2c17ac1ac91467f1d2fb7f4088cd5d0819fb53fac4949866c55a`
- `tenant-administration-en.png`：`6246988bd5ac1f363693e1772e0b8e9bdc17cfb1ce57c89eec7180638260904e`
- `tenant-administration-mobile-en.png`：`ada46f478359bc9c81d2dd632c21ed9937dd7605d3cdba1f9996fa5cf7c4abce`

## 14. 已知边界与剩余风险

| 优先级 | 边界/风险 | 当前处理 | 上线要求 |
|---|---|---|---|
| P0 | location 尚未完成全部交易服务攻击面证明 | 登录/注册/平台/租户管理已使用权威会话并完成双租户越权拒绝；交易 key/表已 location 化 | 继续完成 Order/Trade/MD/Liq 全 DAO、Topic、缓存、锁和重放攻击测试；GW 保持可选增强而非硬编码 SaaS |
| P0 | 资金流水普通成交使用内存异步队列 | 批量 250、失败重试、优雅停机排空、压力精确核对 | 事务 outbox、不可变复式账本、持续对账 |
| P0 | APS 当前仅验证单一外部源 | Binance Futures 实时 ticker/bookTicker 和 Web Mark/Index 已通过 | 建设多源指数、异常剔除、断源降级与偏离保护 |
| P0 | 无真实钱包和合规 | Deposit 仅测试 | 钱包/KMS/HSM、KYC/AML、提现审批和审计 |
| P1 | 当前容量距交易所目标较远 | 3000×32 实测 taker 232.6 req/s；挂单阶段 p99 803 ms | 分片单写、异步持久化、性能剖析并达到业务 SLO |
| P1 | 私有流和深度流未生产化 | 现有 Topic/Snapshot 可用 | 序号、补发、断线恢复、快照+增量一致性 |
| P1 | 完整账户模式不足 | 核心 long/short 字段和 Cross 配置存在 | 完整单向/双向、全仓/逐仓、统一账户验收 |
| P1 | 订单产品仍不齐 | TP/SL/OCO 已有核心语义 | 追踪止损、Close on Trigger、SMP group、活动单上限 |
| P1 | 多租户控制面仍是第一阶段 | 申请、审批、URL、注册、用户、品种、API Key、Robot 配置、交易记录、设置和审计已验收 | 自定义域名/证书、套餐配额、2FA、完整 RBAC、导出审批和平台分权 |
| P1 | RobotSvr 实现完成但生产证据尚未闭环 | APSSvr 10 档、租户报价、价差内扫单、库存保护、幂等对冲流水和 1 万轮盘口风险测试已完成；公开镜像构建成功 | GHCR 包设为 Public 后执行单 location E2E；使用专用币安测试/小额账户完成真实反向对冲、断网不确定响应和恢复验收 |
| P1 | 单机基础设施 | Docker 单机可恢复 | MySQL/ClickHouse/ZK 集群、撮合热备、PITR、灾备演练 |

## 15. 后续实施顺序

1. 先把核心金融正确性补成生产形态：事务 outbox/复式账本、持续对账、多源指数和标记价、完整账户模式、风险限额、资金费和极端行情回放。
2. 收口服务端权威 location：完成 Order/Trade/MD/Liq 跨租户请求、订阅、缓存、锁、重放和数据库攻击测试；如需前置防御，以可选 SaaS GW 插件实现，保持通用 GW 独立性。
3. RobotSvr GHCR 包公开后执行一键增量部署：先验收 APSSvr 10 档与租户上下 10 档重合、用户价差内挂单被扫、成交持仓、停用撤单和跨 location 隔离；再以专用币安账户验收真实反向对冲及不确定响应恢复。随后补齐追踪止损、Close on Trigger、完整账户模式等交易产品。
4. 完成多租户第二阶段：自定义域名/证书、套餐配额、2FA、平台/租户 RBAC、导出审批、品牌资产和用量计费。
5. 发布版本化 REST/WebSocket API、HMAC/RSA/Ed25519、API Key 权限/IP 白名单、私有流、序号恢复和分层限流。
6. 完成真实钱包、安全合规、高可用、容量、混沌和灾备后，才进入小额内部真实资金灰度。

## 16. 手工验收步骤

1. 打开 Web 地址，使用 `p2buyer` 或 `p2seller` 及运维提供的验收密码登录。
2. 在 Account Info 执行测试 Deposit，并在 Funds 查看流水。
3. 提交远离盘口的限价单，在 Open Orders 确认后撤单，检查余额冻结完全释放。
4. 使用两个无痕浏览器分别登录 `p2buyer` 和 `p2seller`，以相同价格、相同数量提交相反订单。
5. 检查 Recent Trades、Order History、Trade History、Positions 和 Account Info。
6. 点击 Close，确认生成 Market/IOC/ReduceOnly 平仓并最终无仓位、无活动单、无保证金占用。
7. 不要在本环境连接真实钱包或投入真实资金。

## 17. 相关文件

- 用户手册：`docs/USER_GUIDE.zh-CN.md`
- 核心验收报告：`docs/CORE_TRADING_ACCEPTANCE_20260828.zh-CN.md`
- 对标路线图：`docs/BINANCE_BYBIT_ROADMAP.zh-CN.md`
- 自动更新说明：`docs/AUTO_UPDATE.zh-CN.md`
- 数据库证据原始 HTML：`docs/evidence/database-evidence.html`
- 压力测试脚本：`tests/run-core-trading-stress-host.sh`
- 完整验收脚本：`tests/run-core-trading-acceptance.sh`
- 数据库证据脚本：`tests/capture-database-evidence.sh`
