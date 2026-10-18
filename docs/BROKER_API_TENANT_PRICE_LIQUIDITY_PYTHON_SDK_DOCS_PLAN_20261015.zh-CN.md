> **2026-10-19 决策更新（覆盖本文旧的 PRICE_PUBLISH 权限设计）**：Broker 自定义价格仅在 **APSvr** 认证租户 API 会话（LoginSvr 的 `TenantAPI`）并验证消息 `location` 不得指向其他租户；**不检查 PRICE_PUBLISH 专项权限，不要求 `apiKeyType=broker`**。MDSvr 不重复做用户权限认证，负责按租户选择自定义/Binance 有效价格并通过现有行情通道发布，Gateway/Common HA、Trade/Liq 订阅架构不变。此项已在 APS `saas-crypto` 提交并灰度部署，但 Broker 价格实发仍受尚未打通的发布者/配置流程阻挡；详见 [当前实施验收记录](BROKER_API_V1_IMPLEMENTATION_AUDIT_20261018.zh-CN.md) 最新 T 节。

> **实施进度与实际验收记录（持续更新）**：见 [BROKER_API_V1_IMPLEMENTATION_AUDIT_20261018.zh-CN.md](BROKER_API_V1_IMPLEMENTATION_AUDIT_20261018.zh-CN.md)。当前 APS 正式 Handler 默认关闭；MD Broker 独立接收组件测试 15/15 PASS，但可信发布者租约、MD 全量编译及 Trade/Liq STALE 风控尚未打通，Broker API v1.0 未完成 E2E 验收。请按该记录中的最新日期和 Git SHA 接续开发，勿将原设计目标误当完成状态。

# OpenTradingCore Broker API v1.0：租户自定义价格、流动性、SDK 与 API Docs 一体化开发及验收方案

> 状态：设计提案 / 待开发、待验收。2026-10-15。目标分支：`saas-crypto`。
> 范围：本方案是**一个完整交付里程碑**，价格发布、流动性切换、Python Broker SDK、对外 API Docs、独立 Broker Demo 与 E2E **一起完成后**才可宣布 Broker API v1.0 验收通过。不得把设计或既有离线测试报告写成已上线结论。

## 1. 目标与非目标

目标：租户使用 OpenTradingCore 现有撮合、账本、持仓、风险、强平及 HA 能力，自行开发 Web/App/OMS/策略；独立决定指数/标记价格来源（SYSTEM/BROKER）和流动性来源（SYSTEM/BROKER），两维独立组合。每租户/市场隔离；外部系统只访问 GW/Broker API，不直连内部服务或数据库。

非目标：通过 Broker API 修改撮合算法、Common HA 协议、分区主从或交易账本；不新增 PriceSvr、OpenApiSvr 或 Broker 专用撮合引擎；不把业务逻辑塞到 GW；不开放租户管理、API Key 管理、资金划转给普通 Broker 交易 Key；不默认允许第三方 `Isdemo=1` 绕开资金/持仓。

### 权威市场主键

内部沿用已有 `Location + MarketIndicator + SecurityID`（及现有分区路由），不要建立另一套不兼容的 Tenant/Symbol 键。认证身份与 Location 从 LoginSvr Session 取得，不信任请求体指定的租户。租户默认配置，预留交易对覆盖；首版 UI 可只开放租户默认设置。

## 2. 现有代码与复用边界（待继续源码逐链核查）

- `com.app.dc.mdsvr` `E2EMarkPriceOverrideHandler` / `E2EMarkPriceOverrideService` 已有 Location/SecurityID 作用域、MD Primary 验证、内存 override、Index/Mark/Funding 和 TTL；但 E2E Token/默认关闭、本地 ConcurrentHashMap、过期回退 system 只适合测试，**禁止原样对外开放**。
- MD `TradeFacade.effectiveMark()`、`publishTenantMarkPrice()` 已有共享价格按租户传播路径，生产化应复用概念并隔离测试逻辑；当前仅遍历已存在本地 trade stream 的市场，必须补无成交市场的有效价初始化/订阅恢复。
- APSvr 有 `dc.aps.p.**` 等既有 Topic；正式修改前要追踪 APSvr 发布者、MD 订阅器、Trade/Liq 消费器、TopicUtils、IndexFacade 的实际消息协议，避免凭设计示例重命名现有 Topic。
- `dc-quant-deploy/docs/ROBOT_EXTERNAL_STRATEGY_ARCHITECTURE_20260902.zh-CN.md` 规定 Robot 只走 GW，不直连 Order/Trade/MD/MySQL；这是目标边界，不等于当前部署完全达到。
- `BROKER_READONLY_API_ACCEPTANCE_20261013.zh-CN.md` 指出 Broker 当前 Demo 无 Key、真实代客 E2E 未完成。`BROKER_API_E2E_IMAGE_REVIEW_AND_PROJECTION_20261009.zh-CN.md` 区分镜像/离线门禁与真实成交证据；不得复用旧报告冒充本次验收。
- 早期 `CRYPTO_OPEN_API_V1.zh-CN.md` 曾提出宽泛 Tenant/Broker 管理权限；本版**明确以当前产品边界为准**：Broker 交易面不开放客户管理/资金划转；若第三方要独立开户与资金管理，另行建立交互式 Tenant Admin 或单独受控管理集成，不能隐式提权。

## 3. 目标调用链

```text
租户自建 Web/App/OMS/MarketMaker/PricePublisher
      |  Broker Python SDK (服务端保管 Secret)
      v
Gateway API (认证、通用路由、限流、透传；无价格/租户业务判断)
      +--> LoginSvr：Broker 身份、Session、独立权限 PRICE_PUBLISH
      +--> APSvr：publishBrokerPrice Handle -> 系统/租户原始价格事件
      +--> OrderSvr：客户下单、撤单、活动委托；撮合逻辑不变
      +--> TradeSvr：余额/持仓；校验有效价格及健康状态
      +--> AdminSvr：历史订单/成交；交互式租户价格/流动性配置
      +--> MDSvr：盘口/K线/实时订阅
APSvr --> MDSvr：共享 SYSTEM 价格和按租户的 BROKER 价格
OrderSvr --> MDSvr：租户市场订单簿与成交
MDSvr --> TradeSvr / LiqSvr：租户有效 Index/Mark/状态/版本
AdminSvr --> 配置事件 --> MD 与 RobotSvr
RobotSvr：仅 SYSTEM 流动性租户启动系统报价/Tape
```

价格不决定 Last Trade、OrderBook、K 线；这些仍源于真实撮合与成交。系统 Robot 若用于 BROKER 价格 + SYSTEM 流动性组合，其参考价格必须使用该租户有效价格，不能悄然引用 Binance。

## 4. APSvr Broker Price Publishing

新增正式业务 Handle（建议名 `publishBrokerPrice`，具体命名按既有 Handler 路由约定），继续使用 GW `serverName/method/content` envelope。**不要求额外 REST 服务**。支持单条/批量、IndexPrice + MarkPrice 同批快照、Decimal 字符串、marketIndicator/securityId、sourceTime、序号，返回逐条结果。Broker Key 所属 Location 在服务端注入；严格验证 Session 类型、独立 `PRICE_PUBLISH` scope、租户/市场已开启 BROKER、市场启用与价格精度、正数/时间偏差/跳价限幅/速率。默认 Broker Key **不授予**价格发布；Trader Key 不可发布。

发布者租约/epoch 由可信服务端发放；对同一租户市场的后继序号、重传、旧连接、旧 epoch 做 fencing 与幂等。不要每条行情请求 ZK 投票；租约切换执行可信授权，热路径轻量检测。发布结果语义要区分“APS 接受”与“MD/下游已经应用”，需要状态/ack 与监控；HTTP 适合作为第一版，后续可增加 Broker 上行 WS 批量推送以降低高频成本。

建议**内部逻辑**区分：
```text
system: MarketKey -> Index/Mark snapshot （共享一份）
broker: TenantMarketKey -> Index/Mark snapshot
```
Topic 实际格式在读完现有 `dc.aps.p.**` 等生产路径后确定，Broker 原始事件必须携带 Location，不能只按 SecurityID 区分。指数和标记价格作为同一个版本快照，避免不同源混用；不强制将每一份 SYSTEM 价格按 200 租户复制为源 Topic。

## 5. MDSvr 生效价路由与风险语义

建立正式 `TenantPriceService`（或在现有 IndexFacade/TradeFacade 中抽象同等职责），复用已有租户数据模型；保留 E2E Override 独立、默认关闭，不作为生产认证路径。

- `SYSTEM`：读取共享系统价格。
- `BROKER`：只读取该租户市场经验证的 Broker 价格；不存在/过期返回 `STALE/UNAVAILABLE`，**严禁自动回退 Binance**。
- 按 `configVersion + publisherEpoch + sequence` 原子切换生效价；旧 epoch、旧配置版本/序号不可覆盖新版本。
- 配置切换前核验新来源是否准备好；切换中暴露 `SWITCHING` 并防止并发错发；切换成功向消费者广播生效配置版本/价格状态。
- 供 Trade/Liq 的消息保留已有租户市场 Topic/字段契约，扩展必要的 source、version、sequence、priceStatus，而非重建两种下游协议。
- 初始化、Trade/Liq 重启重新订阅、无本地成交记录、MD 主切/重放，都必须拿到最新且新鲜的有效价格。Snapshot 恢复只证明状态完整，不代表行情新鲜。
- `PRICE_STALE` 时 Trade/Liq 对新的风险敏感操作执行明确定义的 fail-closed 保护；不得用陈旧 Mark 新发起强平。撤单、减仓等允许策略须单列并测试；不可简单把所有交易无差别暂停。账本数据不重置。
- MD/Trade/Liq 之间需要明确应用水位与重连快照；测试两种租户同 Symbol 互不污染。

## 6. 流动性来源 SYSTEM/BROKER（互斥）

租户 UI 和配置存储两独立字段 `price_source`、`liquidity_source`，各支持 SYSTEM/BROKER。SYSTEM 使用系统 Robot/Tape；BROKER 禁止平台 Robot/Tape 向该租户新增订单，允许租户独立做市程序通过标准 Broker 下单撤单。普通 Trader 不受影响。

切换 SYSTEM→BROKER：写 `SWITCHING`/configVersion → Robot 停新单 → 按**系统 Robot 自有身份**撤单并确认（绝不撤全租户订单）→ Tape 停止 → 提交 BROKER 生效。反向切换要显式处理外部做市挂单（仅授权专用做市账户），不得擅自撤销普通客户单。失败可重试、可审计、不得短暂双系统做市。Robot scheduler、进程恢复、租户自动审批/启用及 Tape 触发处都要执行模式门禁，不仅仅 UI 隐藏开关。Broker 标准做市订单按真实资金/持仓规则处理，不能直接对外开放 `Demo/Isdemo=1` 特权。

## 7. AdminSvr/Tenant Web 配置

在交互式租户管理新增 Trading Configuration：
- 默认 Price Source、Liquidity Source（可扩展 symbol override）。
- 当前 Index/Mark、Last Update、Publisher、Ready/Stale/Unavailable、当前 Config Version、切换状态。
- 系统 Robot/Tape 状态与委托清理状态；BROKER 模式系统参数置灰。
- 开启/关闭/切换有审计日志、角色权限、失败重试与状态查询。

配置常驻内存，事件驱动刷新；不要每个价格 Tick 查询 MySQL。数据库字段/DDL 必须先核对实际 AdminSvr schema 再实现；不直接照设计文档的示例 DDL 建表。

## 8. Broker Python SDK（与本次交付同步完成）

公开一个稳定 Python SDK（优先），Trader/Broker 共用签名、Session、request/reply、错误模型、限流、重连与 WebSocket 传输。Broker API 的 `customer_id` 应完整贯穿下单、撤单、活动单、历史、余额、持仓、客户私有订阅；接口不能默认为 Broker 本人账户，更不能允许跨租户。SDK 中隐藏内部 `serverName` 与 `method`，但遵从服务器实际协议和 ClOrdID/ExecID 的权威约束。示例：
```python
broker = BrokerClient(api_key="...", secret="...")
broker.place_order(customer_id="customer-1", symbol="BTCUSDT", client_order_id="c-001", ...)
broker.get_positions(customer_id="customer-1")
broker.publish_price(symbol="BTCUSDT", index_price="68000", mark_price="68010")
broker.subscribe_orders(customer_id="customer-1")
```
示例是目标接口，非现有已完成能力。必须实现：
- 自动重连、重新认证、重新订阅、快照+增量、序列 Gap 检测与补拉；
- 网络超时不盲目重发委托，先按 `ClOrdID` 查询；成交按 `ExecID` 去重；
- 精度使用 Decimal/字符串，健壮异常码和超时行为；连接与 Key Secret 只在第三方后端；
- Broker 发布价格、Price Status、做市所需 orderbook/trades、批量撤单；
- Python 包规范、安装、示例、单元测试、基于真实 Demo 的联调测试。
Java SDK 可后续分阶段交付，但此次对外完成标准至少包括 **Python SDK**。

## 9. API Docs 同步完成及发布

`opentradingcore-api-docs` 作为独立对外文档仓库（确认最终实际路径/owner）。文档面向正式开发者而非内部运维，单页分类导航、可展开 endpoint/参数/响应、清晰中英文；不出现内部分区、Common、调试 E2E Token、管理数据库细节。必须包含：
1. Trader 与 Broker 认证、权限和申请位置；明确不公开租户管理、Key 管理、资金划转给普通 Broker。
2. Broker customer_id 语义、交易/撤单/查询/持仓/余额/委托与成交历史（以实际 AdminSvr 授权路径为准）。
3. 价格发布权限、批量格式、Price Status/TTL、切换及不可回退、示例与错误码。
4. 标准 WebSocket 连接、公开 Topic 与租户私有 Topic、Snapshot/Increment/Sequence/Gap、重连恢复。
5. SYSTEM/BROKER 流动性、专用做市账户、订单幂等与安全边界。
6. Python 安装/使用、独立 Broker Demo 开源链接、curl/SDK 示例。

文档须 CI 构建为静态站点、打包 Docker/Nginx、部署并验证主站 API Docs 导航链接打开**正式新版本**。源码、发布 SHA/digest 与站点内容一致。

## 10. 独立 Broker 示例交易系统

交付一个**不调用官方 Trade Web** 的第三方示例：自建前端与后端；后台保存 Broker Key/映射客户身份；页面显示行情/K 线/盘口、客户切换、委托、成交、余额、持仓；支持代客下单撤单与实时订单状态；单独运行价格发布者和外部做市示例。客户开户/入金由受控交互式管理流程前置完成，不伪装成 Broker 交易 API 能力。

## 11. 分阶段实施（必须联合验收）

- **阶段 A：源码契约确认**：逐文件确认 APS Publisher、MD IndexFacade/TopicUtils/TradeFacade、Trade/Liq 订阅、Admin config/schema、Robot 现有控制点、Broker 的权限/SDK/WS；保存现状调用图、Topic 字段和兼容性表。对照 Common/Trade 尚未合并 PR 的实际版本。
- **阶段 B：服务端**：APS Price Handle/权限，MD 有效价与 HA，Admin/Tenant 配置，Robot/Tape 互斥，Trade/Liq 风控联动；默认 SYSTEM/SYSTEM 不回归。
- **阶段 C：开发者交付**：Python Broker SDK + 标准 WebSocket + 完整 API Docs + 独立 Broker Demo，同步联调，而不是服务端完成才想起文档。
- **阶段 D：真实 Demo E2E**：部署不可变镜像并记录 commit/digest，在隔离测试租户新建 Broker Key/专用客户与做市账户，四种组合全部验证；最后叠加真实 HA 与负载测试。

## 12. 联合验收矩阵及通过门槛

| 用例 | 通过要求 |
|---|---|
| SYSTEM Price + SYSTEM Liquidity | 旧默认租户行为完全兼容、Robot/Tape 挂单/成交正常 |
| SYSTEM Price + BROKER Liquidity | 无系统 Robot/Tape 新增单，外部做市真实下单/撤单/撮合 |
| BROKER Price + SYSTEM Liquidity | MD/Robot/Trade/Liq 均使用本租户有效价，不继续 Binance |
| BROKER Price + BROKER Liquidity | 租户独立控制价格与盘口，第三方 Demo 完成交易全链路 |
| 两租户同品种 | 发布者只能写自身价格，另一个租户永不串价 |
| Broker 断流或无新价格 | STALE/UNAVAILABLE，绝不回退 Binance，禁止过期价新强平 |
| 价格跳变/重放/多发布者 | 精度、限速、权限、fencing、sequence、configVersion 生效 |
| 模式切换及 Robot 重启 | 不双做市、不误撤普通客户委托、失败可恢复 |
| HTTP 不确定结果/WS 断线 | ClOrdID/ExecID 幂等，Snapshot/Increment/Gap 完整 |
| MD/Order/Trade Primary SIGKILL | MD 恢复仍遵守来源隔离与有效期，交易不丢单、不重复成交、无双主 |
| 权威状态核对 | 资金、持仓、挂单、成交、Projection watermark、风险状态一致 |
| 50/200 租户稳态 + burst | 统计 TPS/P99/CPU/GC/内存/磁盘，不预设未经测量性能结论 |
| SDK + Docs + Demo | 仅用公开文档、Broker Key 和 Python SDK 成功运行完整独立交易界面；API Docs Docker 版本已在线核对 |

所有风险敏感错误默认 fail-closed；保留精确时间、脱敏 Location、commit、容器 digest、日志与数据库只读一致性证据。不能以 mock、HTTP 200、旧 E2E 报告代替当前真实验收。

## 13. 交付判定

- [ ] 服务端价格/流动性完成并通过 4 组合
- [ ] Broker 客户权限与 Price Publish 独立 scope、租户隔离完成
- [ ] MD/Trade/Liq 断流保护、价格版本及 HA 验证完成
- [ ] 系统 Robot/Tape 互斥及模式切换完成
- [ ] Python Broker SDK + WS + 幂等完成
- [ ] 独立 Broker Demo 完整跑通
- [ ] 正式 API Docs 更新、Docker 部署、主站链接验收完成
- [ ] 10 → 50 → 200 租户压力、真实 Order/Trade/MD failover、一致性完成
- [ ] 镜像/代码/验收报告 SHA 可追溯

全部勾选前不可宣布“Broker API v1.0 可对外完整商用”。

## 14. 关键架构决定

**APS 接入两种价格、MD 统一选有效价、Trade/Liq 只消费对应租户的有效价、Robot 按租户流动性模式互斥、Broker API 通过现有 GW 服务与 SDK 使用；Common 只负责通用 Snapshot/WAL/Diff/HA，不承载业务价格选择。** 性能优先：不逐 Tick 查库、不把高频行情写入同步交易数据库、不在行情热路径 ZK 投票、不按租户复制共享系统源行情。
