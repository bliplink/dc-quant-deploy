# Broker API v1.0 实施记录｜2026-10-18（进行中，尚未验收）

## 权威依据

`docs/BROKER_API_TENANT_PRICE_LIQUIDITY_PYTHON_SDK_DOCS_PLAN_20261015.zh-CN.md`，目标分支全部 `saas-crypto`。本记录只记本轮已验证的源码事实、已提交的组件和明确缺口，**不能替代联合 E2E 验收报告**。

## A. 源码/消息契约核对

- **APSvr 共享价格来源**：`BNFuturesImpl.subscribeMarkPriceEvent` 将 Binance mark/index 同批填入 `MarketDataSnapshotFullRefresh`；`ClientFacade.onMarkPrice` → `MarkPriceListener` → `GwServerResource.publishMessage`。真实发布 Topic 格式为 **`dc.aps.markprice.<symbol>`**；并非将 `dc.aps.p.**` 当做 Mark Topic（后者是不同的 MD 订阅 handler）。
- **MDSvr**：`IndexInput` / `IndexFacade.markPrice` 接共享 system 价格，缓存于 `htMarkPrice`，由 `TradeFacade.publishTenantMarkPrice` 按本节点已存在租户交易流传播。旧 `E2EMarkPriceOverrideHandler`/`Service` 默认关闭、使用静态 Token、进程本地 ConcurrentHashMap + TTL，**不得直接暴露给 Broker**。
- **下游风险价格**：本轮尚未给 Trade/Liq 安装新的租户 BROKER 生效价消费及 STALE 拒绝逻辑；新模式未启用，默认 SYSTEM 行为不变。
- **Router**：Gateway 仍只承担 Session/通用路由/透传；本轮未修改 Gateway 代码，也未改 Common Snapshot/WAL/HA 协议。
- **鉴权**：现有 `RobotSvr` 真正的签名登录用 `LoginSvr.apiKeyLogin`、Header `apikey/expiry/signature`；签名 `HmacSHA256(secret, UTF8(requestBody + expiry))`，小写 hex；随后用 Gateway **TCP GateWayApi** 建立受 session 身份验证的业务连接。单有 HTTP 登录不表示 HTTP 可以替代所有业务 TCP 操作。
- **仓库依赖现状**：本轮从 GitHub `com.app.dc.mdsvr/saas-crypto@455aa2d` 独立 worktree 执行 `mvn -o -Dtest=TenantEffectivePriceBookTest test`，**在已有** `MdAuthenticatedOrderImageReview` 引用的 `RecoverySourceAttestation.VerifiedHead` 找不到类而编译失败，证明 MD 当前离线 Common Jar 依赖基线未闭合；这不是新增 PricePolicy 导致的编译错误。按不修改 Common HA 的约束，本轮没有硬改 Common。

## B. 已实现并测试

`bliplink/com.app.dc.mdsvr` **`saas-crypto`**：`TenantEffectivePriceBook.java` 与 `TenantEffectivePriceBookTest.java`，提交见 GitHub 历史：
- 默认 SYSTEM 使用一份共享市场价，避免按租户复制系统源 Tick；
- BROKER 模式对同 `Location+MarketIndicator+SecurityID` 采用租户独立 Index/Mark 同批快照；不存在或超时返回 `UNAVAILABLE/STALE`、不读系统价；
- `configVersion`、可信 `publisherEpoch`、`sequence` 单调 fencing/幂等；来源切换清空旧 broker 价；过期并不延长旧时间窗；
- 价格正值/精度/时间窗口/TTL 输入限制；不在价格热路径读 MySQL 或执行 ZK 投票；
- **Java 8 独立编译 + JUnit 4：7/7 PASS**（其所在 MD 模块整体 Maven 编译仍被上述原有 Common 依赖阻挡）。
- **重要：此类当前不接入 MD 热路径，APS Broker 正式 Handle、认证、受信 epoch、租户配置分发、Trade/Liq 风控还没上线。属于安全的基础规则代码，而非 Broker 价格功能已交付。**

## C. 尚未完成（全部保持 FAIL/未测状态）

1. APS `publishBrokerPrice` 正式 Handler：从真实 Gateway Session 获取 Location、Broker scope `PRICE_PUBLISH`、应用受信租约/epoch、精度/跳变/限速/审计；租户位置不得来自 body。
2. AdminSvr Tenant Web：`price_source/liquidity_source` 双字段及可重试状态机、配置版本审计、专用 Broker 做市用户隔离和系统 Robot 自有委托清理；此前租户表并无这两个字段，DDL 必须经过 schema 评审。
3. MD 生产数据面：真实 APS 生产 Topic/消息带 Location，broker index/mark 同批版本推送，系统/租户生效价切换和重启 Snapshot/增量恢复；不能复用 E2E Token。
4. Trade/Liq PRICE_STALE 处理、重启/主切价格状态及新强平 fail-closed。
5. Broker customer_id 权限边界、代客下单/撤单/活动委托、历史 AdminSvr、余额持仓、多客户同租户隔离。
6. Python SDK 真实 TCP/HTTP Session、WebSocket 重订阅/Gap/补拉，独立 Broker Demo 完整交易界面，API Docs 代码、静态镜像和站点发布。
7. 四种来源组合 × 两租户同标的隔离 × 各种故障/价格过期/旧发布者测试、10→50→200 租户负载、真实 MD/Order/Trade 故障恢复、权威账务对账：**均未执行、不得宣称通过**。

## D. 部署与风险边界

现有 Mac mini Demo 的 `GW7XMI` 正在用 SYSTEM/SYSTEM 完成 Robot 自动报价（40 笔活动单），**不因 Broker 未完成模块而切换其价格/流动性来源**。本轮不改运行镜像、不运行 SIGKILL、不凭页面 HTTP 200 宣称 Broker v1.0 验收成功。

实现阶段完成后，独立隔离 Broker 测试租户采用新 Key 和客户，先本地测试，再不可变镜像滚动部署，记录源码 commit / image digest / 数据库读数 / 时间 / 错误码。测试结果必须填入完整矩阵：价格数据隔离、互斥做市、行情新鲜度、Replay/Fencing、WS Gap、客户端幂等、四组合、故障恢复、50/200 租户性能数据。

> **总体状态：Broker API v1.0 尚未完成，不具备按本方案正式发布的条件。**


## E. 本轮新增提交（补充实测）

- `com.app.dc.mdsvr/saas-crypto`：`TenantEffectivePriceBook` 实现与 JUnit 4 测试分别提交 `9b0b8a3` 和 `5cff93f`，7/7 standalone PASS；MD 整体 Maven 受已有 Common `VerifiedHead` 依赖阻塞，**没有发布新 MD 镜像**。
- `com.app.dc.managersvr/saas-crypto`：`RobotRuntimeService.listRunnableSql` 加入 `t.liquidity_source='SYSTEM'` 与 `t.source_switch_state='ACTIVE'` 正向名单；正式从 LIST_RUNNABLE 中排除 BROKER 与切换中的租户。源代码 `ef8857a`、定向测试 `de14759`，Manager Maven 3/3 PASS。**需先应用新增迁移再部署 Manager**；本轮没有在生产 Demo 应用该迁移、也未启用 BROKER 切换。过滤已有 Robot 不等于完成自有订单撤单/切换状态机，此项仍未验收。
- `dc-quant-deploy/saas-crypto`：新增 `mysql/migrations/20261018_broker_tenant_sources.sql`（`1f5ef70`）。包含相互独立的 `price_source`、`liquidity_source`（SYSTEM/BROKER）、`source_config_version` 与 `source_switch_state`，默认 SYSTEM/SYSTEM + ACTIVE，所有 ALTER 使用 information_schema 存在性判断。**实际在 MySQL 8.0 的独立临时 schema 跑迁移两次均成功**，检查默认 SYSTEM/SYSTEM/1/ACTIVE 后删除测试 schema；现有业务 `dc` schema 未修改。
- `com.app.dc.api.demo/saas-crypto`：新增 `broker-python-sdk/`，包含经过实际 HmacSHA256+Gateway envelope 源码核对的 HTTP Broker Key Login Python 客户端、强制比对 Broker 身份/租户，以及 5 项 Python unittest（5/5 PASS）。`publish_price/place_order/subscribe_orders` **在服务端尚未具备正式协议时故意 fail-closed 报未实现**，未做虚假 Broker 下单，亦未提供真正的独立 Broker Demo。
- 所有上述提交使用 `[skip ci]`。没有修改 Gateway 透传代码，也没有修改 Common HA 实现或执行故障注入。当前 `GW7XMI` 的 SYSTEM/SYSTEM Robot 仍保持 RUNNING，Broker 接口/租户来源切换不允许在当前产品 Demo 直接打开。

**验收结论没有变化**：这些是可追溯基础组件及单测成果，**非 Broker API v1.0 完整交付**。本轮未执行跨服务 Broker price Publish/MD/Trade/Liq 数据流、真实租户隔离、WebSocket、API Docs 发布、独立 Broker Demo、50/200 租户压测或真实 HA failover；任何对应 PASS 都是虚假结论。


## F. 既有 Python SDK 核对与统一决定（2026-10-18）

用户提示此前已有 Python API，重新检查 GitHub 得到确切结果：**`bliplink/opentradingcore-api-docs` 的 `saas-crypto/sdk/python` 已包含独立 `opentradingcore` Python SDK v0.1.0**。源码包含 `opentradingcore/client.py`、`realtime.py`、`tests/test_client.py`、`examples/demo_readonly.py` 与 `pyproject.toml`；之前还构建过 Wheel。其主类 `OpenTradingCoreClient.from_api_key(...)` 允许直接在 Python 传 Key/Secret，无须 shell export。

源代码实查已包含：HMAC-SHA256 登录（Trader `API/trade`、Broker `TenantAPI/broker` 身份校验）、`market_snapshot`、`kline`、`open_orders`、`order_history`（AdminSvr `queryOrder`）、`execution_history`（AdminSvr `queryExecOrder`）、`balances`、`positions`、`place_limit_order`、`cancel_order`，订单写操作不自动重发；`RealtimeTopics`、`DepthSequence` 负责 Topics、Snapshot/diff 和 gap 拒绝错误续接。**尚未实现已验收的公网 WebSocket Transport / Broker `customer_id` 完整授权 / `publishBrokerPrice` / 生产价格状态与发布者租约**。

本轮经 GitHub 读取真实 `saas-crypto` 7 个文件到 Mac 临时目录 `/tmp/otc-canonical-python-sdk-audit-20261018`，执行 `PYTHONPATH=. python3 -m unittest discover -s tests -v`，结果 **12 tests / 12 PASS**。这是 Python 单元测试，**不是**实机 Trader/Broker E2E：没有替代真实 Gateway TCP/WS 和代客委托验收。

**统一决定：既有 `opentradingcore` 是唯一正式 Python SDK**；在此基础上扩展 Broker customer_id、scope、批量价格发布、实时 WS 重连补拉、ExecID/ClOrdID 幂等。原本在 `com.app.dc.api.demo/saas-crypto/broker-python-sdk` 做的 `opentradingcore-broker` 是实验性的签名客户端，并没有已部署的交易能力，不能作为第二套对外 SDK。已在该目录 README 明确弃用指向正式 SDK（`ea92d16`），后续仅保留独立 Broker Demo 对正式 SDK 的调用。

实机现状再次核验：`GW7XMI` 的 `dc_tenant_liquidity_bootstrap=COMPLETE:DONE`，Robot `RUNNING`、40 挂单；业务 `dc` 库的 `dc_tenant` 尚无 `price_source/liquidity_source/source_config_version/source_switch_state` 四列（迁移仅在隔离临时库验证过）。Docker 实际 APS 为 `sha-73e3fd5`、Manager 为 `sha-f8659fb7`、MD 为旧本地 cluster-dev 镜像，未安装 Broker 模式新代码；API Docs 容器运行旧 `sha-91ba653` 镜像并健康，但新的 Broker API Docs 没有编译发布。主站 HTTP 200，`docs.opentradingcore.com` 在本机 DNS 无法解析，不能声称新 Docs 公网地址已验收。

**总体判断：旧 SDK 可复用，且 12 个单测通过；Broker v1.0 整体仍属于服务端基础代码阶段，关键价源开关、权限、实际 WS/代客链路、独立 Demo、完整 E2E/50-200 租户压力及 HA 验收尚未完成。**


## G. 新一轮实际交付：显式价格权限 + canonical SDK Broker 客户交易封装（2026-10-18）

本轮没有重建 Mac Demo 或修改运行中的 APS/MD/Trade/Order/Robot 镜像；先提交独立、安全、可单测的代码。当前产品 Demo 继续 SYSTEM/SYSTEM，不宣称 Broker v1 完成。

### 已提交到各仓库 saas-crypto

1. **`bliplink/com.app.dc`（公共业务 API 契约，并非 Common HA）**：`DcOpenApi.Scope.PRICE_PUBLISH` 显式 Broker Scope；`isBrokerScope` 接受它，但 `BROKER_DEFAULT` **不包含它**，Trader/Tenant 原有 Scope 不继承价格发布权限。代码 `de76d8c`，测试 `e85100e`；Java 8 单文件编译、JUnit4 **6/6 PASS**。模块完整 Maven 在 Mac 本地缓存缺少 `io.github.bliplink:com.app.common:3.0.20` 时依赖解析失败，不以此修改 Common HA 状态机。
2. **`bliplink/com.app.dc.apssvr`**：`BrokerPriceAccessPolicy` 和 `BrokerPriceAccessPolicyTest`，分别 `31b1249`、`b8b2dbc`。严格要求经过 LoginSvr 登录的 `TenantAPI/broker`、完整词元匹配 `PRICE_PUBLISH`、从 Session 得到租户并拒绝 body 冲突、单批指数/标记价格正数和精度、事件时间新鲜度及 TTL 限制。Java8 独立 JUnit4 **5/5 PASS**。**这只是正式入口的授权/校验组件，尚未安装 `publishBrokerPrice` Handler、可信发布者租约或消息发布，不能发正式 Broker Price。**
3. **`bliplink/opentradingcore-api-docs` 原有 canonical Python SDK `sdk/python/`**：继续使用 `opentradingcore` 0.1.0，扩展以下 explicit customer API：`place_customer_limit_order`（`OrderSvr/placeOrder`，要求强制 `ClOrdID`）、`cancel_customer_order`（要求独立撤单 `ClOrdID`）、`customer_order_history`（`AdminSvr/queryOrder`）、`customer_execution_history`（`AdminSvr/queryExecOrder`）。全部限定 `TenantAPI/broker` Session + `ORDER_READ/WRITE`；客户 user_id 必须显式传入、location 从登录 Session 派生、SDK 不自行跨租户或自动重试不确定的写请求。客户端代码 `02c05aa`、测试 `a3b707b`；在 Mac 运行完整 Python SDK 单元测试 **15/15 PASS**；新增隐藏 Key/Secret 输入、只读客户历史示例 `examples/demo_broker_readonly.py`（`3dc5a91`）、README 用法（`54ea07b`）。

### 额外核对的服务端约束与开放问题

- 从最新 `com.app.dc.ordersvr/saas-crypto` 源码确认其 `SessionOrderAuthority.scope` 调用 `OpenApiAccountAuthority.resolve(session, location, userID, ORDER_WRITE, true)`，Broker 须为同租户启用的 TRADER 客户；`com.app.dc.adminsvr/saas-crypto` 当前 `LegacyOrderQueryScope` **已经**调用 `OpenApiAccountAuthority.resolve(..., ORDER_READ,false)`，无需用本机过时 `.work/adminsvr` 版本覆盖。仅源码确认；尚需用真实 Key 做 Order/History 端到端验收。
- 以上 Python Broker 委托接口单元测试用注入 Transport 模拟 Gateway，验证分区路由、大小写正确的 `Location/UserID`、明确 customer_id、Broker 权限及无重复请求；**并未证明现在的公网站点已经支持此传输，更未验证实际成交和资金归属**。
- 严禁仅放开 APS E2E 测试 Token：正式 APS Price Handler 还须引入真实 Broker Session、`PRICE_PUBLISH` 授予流程、按租户价格模式校验、可信 Publisher Epoch/Fencing、审计及频率限制；MD 旧 E2E 内存价源不能替代生产租户价格状态，Trade/Liq 仍需 STALE fail-closed。
- **当前仍未完成**：真实 APS Handle 接 MD→Trade/Liq、双来源热切换与自有系统挂单撤销、Broker customer 资金查询权限、真正 WebSocket Gateway 传输和 Snapshot/Gap 恢复、API Docs 新 Docker 镜像/公网发布、独立可交易 Broker Demo、四组合与跨租户隔离 E2E、10/50/200 租户故障与性能压测及 HA 一致性验收。

### 下轮顺序

先确定并打通 APS 正式发布入口 + 签名发布者租约 → MD 有效价按租户来源选择并隔离下游 STALE → Admin/租户流动性切换撤销老系统 Robot 委托 → 真实独立 Broker Key、客户与 SDK 委托 E2E → WebSocket/Docs/Demo → 镜像/故障和 50/200 租户验收。期间保持 Gateway 透传与 Common HA 架构不变，Mac Demo 只在安全的联合验证门槛达到后再升级。


## H. 2026-10-18 19:32 CST｜APS 正式 Broker Price Handle 和 MD 系统价隔离（默认关闭）

本轮完成了两个安全闭环的**代码层增量**，并同步更新至各仓库 **`saas-crypto`**，所有提交均带 `[skip ci]`。

### APSvr：公开方法名已保留，尚无可信租约实现

- `com.app.dc.apssvr@saas-crypto` 新增 `@Service("publishBrokerPrice")` 的 `PublishBrokerPriceHandler`（`5a60569`）、`BrokerPricePublishReq`（`3904dce`）、`VerifiedBrokerPricePublisher` 发布者接口（`267e1e1`）、测试（`d3f6760`、`525e494`），以及只在显式配置 `broker.price.publish.enabled=true` 时初始化 APS LoginSvr Session Cache 的 `APSService` 修改（`b6ec8ea`）。
- 入口使用真实 `message.getSignalID()` → `LoginSvrClient.get(sid)` 的 Session，要求 `TenantAPI/broker` + 精确 `PRICE_PUBLISH` 权限；请求 body 中的 `location` 只能与 Session 租户一致。Index/Mark 同批、正值/精度/TTL/时间窗口校验，并检查请求 `config_version>0`、`sequence>0`。
- **明确默认 FAIL-CLOSED**：`broker.price.publish.enabled` 默认 `false`；即使设置 `true`，若 Spring 中没有实现通过租户 BROKER 配置、已认证发布者 Epoch、持久化 Sequence/Fencing、MD→Trade/Liq 就绪/审计的 `VerifiedBrokerPricePublisher`，仍返回 `503 BROKER_PRICE_PIPELINE_NOT_READY`，**不发布任何价格消息**。当前故意不注册任何此实现，防止测试 Token 或伪造 Epoch 绕过硬门禁。未来可信租约接好时，Topic 才会是 `dc.aps.markprice.<authenticated-location>.<securityId>`，消息携带服务端可信的 Epoch/配置版本/序列。
- **实测**：Mac JDK8，APS Maven offline **全量 40 tests、0 failed、0 errors、0 skipped，BUILD SUCCESS**（含入口默认关闭、仅开启开关不能绕过缺失租约两项测试，以及 Broker Scope/时间戳/跨租户校验）。这次是完整 APS 模块 Maven 构建测试，不是仅文件级单测。

### MDSvr：阻断 Broker 租户 Topic 污染共享系统价格

- `com.app.dc.mdsvr@saas-crypto` 新增 `SharedMarkPriceTopicGuard`（`5003ae9`）、对应 JUnit 4 测试（`130c730`），并在 `IndexInput` 真实 MarkPrice 接收入口接入（`8b7c10f`）。
- 原 `IndexClient` 订阅 `dc.aps.markprice.**`，会覆盖标准四段 Topic `dc.aps.markprice.BTCUSDT` 和未来五段 `dc.aps.markprice.<Location>.BTCUSDT`。现在只允许四段系统 Topic、空 payload Location、与 payload SecurityID 同标的通过 `indexFacade.markPrice(t)`；带租户、标的错配、通配符、异常 Topic 均无法写入全局 mark-price 缓存。
- **实测**：独立 Java8 + JUnit4 `SharedMarkPriceTopicGuardTest` **4/4 PASS**。MD 全模块 Maven 仍可能被先前 `RecoverySourceAttestation.VerifiedHead` 与本地 Common 依赖不一致阻挡，**本轮没有宣称 MD 全量构建/上线成功**；未来 Broker 租户价格必须走单独的授权消费者，严格配置版本/Publisher Epoch、Seq、Snapshot/Diff 和 STALE fail-closed。

### 生产运行态与后续未完成项

- 本轮**没有替换 Mac 任何 APS/MD/Trade/Liq/Robot 镜像**，也没有修改生产 Demo 业务 `dc_tenant` 表（新增 `price_source/liquidity_source/source_config_version/source_switch_state` 字段仍为 0/4）。现有 Demo 按 SYSTEM/SYSTEM 原路径运行，确保无未经授权 Broker 价格进入真实强平逻辑。
- 2026-10-18 19:32 CST 实机复查：`GW7XMI` `COMPLETE:DONE`、Robot `RUNNING`、40 个活动委托；主站 `https://opentradingcore.com` 和交易站 `https://trade.opentradingcore.com` 均 HTTP 200。
- **下一步关键链路尚未通过**：实现经过正式认证的 Publisher Epoch 租约和可持久验证的 Source/Sequence 提交事务；MDSvr 安全 Broker 入站和 SYSTEM/BROKER 来源状态分发；Trade/Liq 对 STALE 价的拒绝/恢复；Admin Web 有审计的租户价源切换及系统自有报价撤销；完成全量 APS→MD→Trade/Liq 双租户 E2E 之后，才允许启用 `broker.price.publish.enabled` 和替换 Demo 镜像。独立 Broker Demo、公开 WS、API Docs Docker 部署、200 租户压测和 HA 故障恢复仍未做，**不能宣布 Broker v1.0 整体验收**。


## I. 2026-10-18 19:52 CST｜MD Broker 独立接收入口与可信校验合同已提交（最新进度）

**阶段结论：MD 已有独立、默认关闭的 Broker 价格接收及租户状态机调用；未获得可信配置/租约服务证明的价格不能进入接收端。真实风险价格下游尚未打通，故依然禁止启用 Broker 模式。**

### 本轮实交付代码（`bliplink/com.app.dc.mdsvr/saas-crypto`）

| 代码或测试 | GitHub 提交 | 行为 |
|---|---|---|
| `BrokerTenantPriceEvent.java` | `42d62bb` | 严格解析 `dc.aps.markprice.<Location>.<SecurityID>` 五段 Topic，核对 payload 同租户/币种、Index+Mark 同批值、MarketIndicator、时间/TTL、configVersion、publisherEpoch、sequence；旧系统 Topic、非法 ID、长度/数字不符均拒绝 |
| `VerifiedBrokerPriceAdmission.java` | `3bd5813` | 可信配置/Publisher Epoch/Sequence **必须由独立校验器认可并先持久化**，不能把 APS 消息内声称的 Epoch/版本视为权威 |
| `BrokerTenantPriceReceiver.java` | `bf240a2` | 在批准前不变更租户价格状态；先做价格合法性 preflight，再比对可信准入结果六个字段，最后交给原 `TenantEffectivePriceBook` |
| `BrokerTenantPriceInput.java` | `13a0c7e` | 新的 Spring 订阅器，`broker.price.receive.enabled:false` 默认不订阅；开关开启而无真实 `VerifiedBrokerPriceAdmission` 实现时直接抛 `BROKER_PRICE_ADMISSION_NOT_INSTALLED`，不会误收价；只更新独立内存租户价格状态，不触及系统价和真实 Trade/Liq |
| `IndexClient.java` + `MDStart.java` | `ec2fea0` + `ad26891` | 注册独立 Broker Map 类型订阅；仅显式开启时在 MD 后台订阅重试链路中安装，不改原四段 SYSTEM Mark Topic |
| `TenantEffectivePriceBook.validateQuote()` | `9e32dd6` | 在调用持久化准入/序号提交前验证时间、TTL、价格有效性，避免非法报价先消耗持久序号 |
| `BrokerTenantPriceReceiverTest` + `BrokerTenantPriceInputTest` | `e19df98` + `bf47af6` | 覆盖系统/租户及两币种隔离、Topic 与 payload 不一致、无校验器/伪造 Epoch、Sequence replay、过期后拒绝回退系统价、非法数字、默认关闭 |

### 测试与已知阻塞（不隐瞒）

- Java8，JUnit4 + 本地框架最小 Stub 进行新组件**独立隔离编译与测试：14/14 PASS**。此外共享价 Topic 严格匹配的 JUnit 之前已 4/4 PASS。Stub 编译覆盖 `BrokerTenantPriceInput` 缺失依赖下的功能开关路径；**不等于真实 Gateway 消息订阅 E2E**。
- 使用 MD 原生 `mvn -B -o -Dtest=BrokerTenantPriceReceiverTest,BrokerTenantPriceInputTest test` 时，依旧在旧 HA 源码 `MdAuthenticatedOrderImageReview.java` 中 `RecoverySourceAttestation.VerifiedHead` 类型缺失处**编译失败**，测试尚未进入 Maven；这与本轮价源接收实现无关。为保持 Common HA 架构不变，未随意修改其恢复状态机、未强行发布 MD 镜像。
- 可信 `VerifiedBrokerPriceAdmission` 是接口契约，**当前没有可用实现或发布者持久租约/ConfigVersion 事务**；因此 Broker 输入依然处于明确的 FAIL-CLOSED 状态，`broker.price.receive.enabled` 不应开启。
- SDK、APS 和原 Robot 服务的完成状态详见本记录 F/G/H；**不能把已有的 14 项单测当成整个 Broker API 已经部署或通过压力/故障验收。**

### 最新 Demo 运行态（2026-10-18 19:52 CST）

- 实际 Mac Docker 的 APS `ghcr.io/bliplink/apssvr:sha-73e3fd5`、MD A/B/C `dc-saas/mdsvr:cluster-dev-fenced-transport-20261016`、Trade A/B `trade438-carriedepoch-2a043ac-20261018` **均未替换为这轮实验代码**，Gateway 透传和 Common HA 均未修改。
- `dc.dc_tenant` 中 Broker 双来源配置字段仍为 **0/4**（迁移未应用产品库），`GW7XMI` 仍为 SYSTEM/SYSTEM：`COMPLETE:DONE`、Robot `RUNNING`、活动挂单 40，主站/交易站 HTTP 200。

### 下一阶段必须推进（按依赖顺序）

1. **真正的可信租约/配置事务**：Admin/APS/MD 验证租户选 BROKER、`PRICE_PUBLISH` Key Scope、PublisherEpoch 唯一性、签名/持久序号、配置版本、失效时间，提供 `VerifiedBrokerPricePublisher` 与 `VerifiedBrokerPriceAdmission` 的生产实现，校验不是靠调用方自报。
2. **MD→Trade/Liq 价格状态分发**：显式 READY/STALE/UNAVAILABLE、Snapshot/Diff/恢复重订阅、故障/超时禁止回落 Binance，不修改 Gateway/Common HA 通用机制。
3. **来源切换完整状态机**：Broker 流动性激活前禁止系统 Robot 继续下单，并撤销系统 Robot 现存委托（按 owner ID），确认完成后才 ACTIVE；切回 SYSTEM 需安全预热。
4. 完成 Canonical Python SDK Broker 查询/下单实网验证、实时 WebSocket 连接和 Gap 补拉、单页 API Docs、独立 Broker Demo、两租户×四来源组合、完整资金持仓成交对账，最后做 10→50→200 租户负载及 HA 故障恢复。**全部还没有满足正式验收门槛**。

**记录规则**：后续每一批真实代码提交、单测、Mac 镜像发布或故障注入都往此文档追加日期、仓库/分支/Git SHA、测试数字、环境状态、未通过项，不以无证据“全部完成”替代验收。


## J. 2026-10-18｜MD 订阅回调完整性补测与进度更新（最新）

- 基于前一阶段新增的 `BrokerTenantPriceInput`，使用可捕获 `BaseApi.IMessage<Map>` 订阅回调的测试桩直接触发：可信事件接收 1 次、重复订阅仍只注册 1 次、伪造租户 Topic/不合法 SYSTEM Topic 共拒绝 2 次；`T1` MarkPrice 为独立 Broker 价、`T2` 无 Broker 价。
- 拒绝事件处理改为捕获 `RuntimeException` 并累加 `rejectedCount`，避免异常事件或未准备好准入提供者在消息回调里触发订阅线程崩溃；未吞掉 JVM 级致命错误。代码 `com.app.dc.mdsvr/saas-crypto@68fde38`，测试 `@e4a61ab`。
- Java8 独立测试现为 **15/15 PASS**（`BrokerTenantPriceInputTest` + `BrokerTenantPriceReceiverTest` + `TenantEffectivePriceBookTest`）；另有 SYSTEM Topic Guard **4/4 PASS**。完整 MD Maven 仍被已有 HA `RecoverySourceAttestation.VerifiedHead` 类型缺失阻塞，不能作为模块全量验收。
- Mac 主站、交易站再次实测 HTTP 200；本轮未部署或替换任何 MD/APS/Trade/Liq/Robot 生产 Demo 容器，亦未改 Common 或 Gateway。当前依旧 **Broker 价格发布/消费实机 E2E 未通过**，需生产可信租约/数据库配置及下游风控状态链路，不能仅开两个 feature flag。


## K. 2026-10-18 20:00 CST｜MD 全量 Maven 编译及回归解锁，启动联调测试

**问题根因已定位**：MD 编译报错 `MdAuthenticatedOrderImageReview -> RecoverySourceAttestation.VerifiedHead` 并非 Broker 新代码本身错误。MD 经 `com.app.dc 0.0.4-SNAPSHOT` 传递解析的是旧 `com.app.common:3.0.17`，该版本没有 `VerifiedHead`；本机 Common 修复分支已有 `3.0.22-SNAPSHOT` Jar，此版本存在 `VerifiedHead` 且不需要改 Common HA 源码。

**本轮实测**：在独立 MD worktree `/tmp/otc-broker-md-price-v1-20261018` 内通过直接显式依赖 `io.github.bliplink:com.app.common:3.0.22-SNAPSHOT` 对齐二进制依赖，执行：

```bash
JAVA_HOME=/Users/kong/Library/Java/JavaVirtualMachines/zulu-8.jdk/Contents/Home \
  /Users/kong/.opentradingcore/ha-unified-validation-20261015/tools/apache-maven-3.9.16/bin/mvn -B -o test
JAVA_HOME=/Users/kong/Library/Java/JavaVirtualMachines/zulu-8.jdk/Contents/Home \
  /Users/kong/.opentradingcore/ha-unified-validation-20261015/tools/apache-maven-3.9.16/bin/mvn -B -o package
```

结果 **MD 全量 165/165 PASS，0 fail，0 error，0 skipped，BUILD SUCCESS**；包含 Broker 入站/消息隔离相关 **19/19 PASS**。jar 输出 `target/com.app.dc.mdsvr-0.0.1-SNAPSHOT.jar`，本地大小约 199 KiB。GitHub `com.app.dc.mdsvr/saas-crypto@aaa8f8be` 已提交显式二进制依赖对齐。**此修改是 MD Maven 依赖解析，不涉及 Common HA 状态机实现。**

**发布门禁**：Common `3.0.22-SNAPSHOT` 目前仅确认本机离线仓库及 HA 修复分支源码，不能据此假定在中央仓库已发布并可以从任意干净构建机检出。推正式镜像前必须固定可重现的 Common Jar + SHA、建立发布凭证来源，避免部署引用旧 `3.0.17` 或误拉错误版本。尚未滚动替换 Mac Demo MD 容器。

**重要剩余缺口**：上述是服务代码完整编译/单测，不是 Broker 模式生产完整 E2E；`VerifiedBrokerPricePublisher` 和 MD `VerifiedBrokerPriceAdmission` 仍无经过租户生效配置与授权租约证明的生产实现。缺少下游 Trade/Liq 的 STALE/UNAVAILABLE fail-closed、Broker 模式安全切换及撤单、Python SDK/WS/Docs/Demo 实网验收，暂不开 Broker feature flags。现有 `GW7XMI` SYSTEM/SYSTEM Robot 和公共站点保持原样。

**后续必验顺序**：签名发布者租约与持久 Replay/Fencing → MD 租户来源配置入站、重启 Snapshot/序号追平 → Trade/Liq 风控状态正确传播 → SYSTEM/BROKER 双来源安全切换与 Robot 自有单撤销 → 2租户×4组合 E2E → WebSocket/SDK/Docs/Broker Demo → 50/200 tenants + 真实故障恢复及账务对账。


## L. 2026-10-18 20:26 CST｜Admin 流动性两阶段切换、真实 MySQL 集成测试与发布前门禁

### 新提交代码与验证（当前轮次）

- **AdminSvr `saas-crypto`**：新增 `TenantBrokerLiquiditySwitch`、`TenantBrokerLiquiditySwitchHandler`、`TenantBrokerLiquiditySwitchReq`，见代码提交 `8b5f4f1`、`0654d4b`、`ac2f710`；默认配置 `broker.liquidity.switch.enabled=false`，须从 LoginSvr Session 取得真实同租户 TENANT_WRITE 管理员身份；请求体 Location 不得越权。只实现 `SYSTEM/ACTIVE → BROKER/SWITCHING → BROKER/ACTIVE`（其余反向模式在安全证明未具备前拒绝）。
- 切换 BEGIN 单事务更新 `liquidity_source=BROKER`、`source_switch_state=SWITCHING`、递增 `source_config_version`，并将该租户全部系统 Robot `enabled=0`，**保留运行时 lease** 等待 RobotSvr 正常执行取消订单/释放租约；在 `SWITCHING` 期间 ManagerSvr 的 `SYSTEM/ACTIVE` 门禁不会再次启动 Robot。
- ACTIVATE 需要同一租户数据库锁、期望的 source_version、Robot `enabled=0`、运行 owner 已释放、Robot 现有报价数为零、SYSTEM maker 用户在 `dc_orders` 的 `New/PartiallyFilled` 且 `leaves_qty>0` 订单为零。所有条件未通过，保持 `SWITCHING` 并拒绝激活；每次成功切换的状态及审计在同一事务提交。**需要注意**：最终切换前还要有权威 Order 路由/未决写入和下游独立 Broker 流动性证据，本提交只完成数据库/Robot 层门禁；不能仅凭 MySQL 投影数据就宣称不再有在途订单。
- **AdminSvr `saas-crypto`** `TenantSettingsService` GET 增加 `price_source`、`liquidity_source`、`source_config_version`、`source_switch_state` 的只读输出（commit `4e3c5ca`）；代码依赖 `20261018_broker_tenant_sources.sql` 先迁移，当前 Demo 未应用迁移。
- **测试**：Mac JDK8 AdminSvr 全量 `mvn -B -o test` **89 项（0 fail, 0 error, 1 skipped）**；新增 `TenantBrokerLiquiditySwitchMysqlIT`（commit `4dba5b9`）利用真实 Docker MySQL8 的**独立临时 Schema**，完整执行 BEGIN → 验证 Robot 仍占有 lease 时拒绝 ACTIVATE → lease 释放但 `New` 订单未撤时再次拒绝 → 标记 Cancelled 及 0 leaves 后成功 ACTIVATE，检查 config_version 与两笔审计事务、价格来源仍 SYSTEM；结果 **1/1 PASS，0 skipped**，测试 Schema 已删除，无生产租户数据修改。日志 `/tmp/otc-broker-admin-switch-mysql-it-real.log`。
- **部署仓库 `saas-crypto`**：新增只读 `tests/preflight-broker-v1-release-host.sh`（commit `14802bc`），检查服务 Up、源配置 Schema 列数、APS/MD/Admin 新 Broker 类是否在运行镜像。该脚本**不是完整业务验收**，只作为部署最低门禁；在 Mac 实机执行返回非零，具体 4 个未通过项：`dc_tenant` Broker 四列当前为 0/4；APS Broker Handler、MD Broker Receiver、Admin Broker Liquidity Handler 均尚未在当前运行镜像。服务本身 8/8 Up；旧 Manager Scheduler 类存在，但不代表 Broker gating 镜像已替换。
- **MD `saas-crypto@aaa8f8be`** 显式 Common 3.0.22-SNAPSHOT ABI 对齐后 Maven 全量 **165/165 PASS**、`mvn package` BUILD SUCCESS；这一结果仍依赖本机缓存的 3.0.22-SNAPSHOT，未验证中央仓库干净重建。Common HA 业务源未修改。

### 当前真实 Demo 与正式交付状态

2026-10-18 20:26 CST：`GW7XMI` 流动性任务 `COMPLETE:DONE`、Robot `RUNNING`、活动挂单 40；主站和交易站均 HTTP 200；没有重建/升级现网容器，**Broker v1 正式接口和独立租户尚未上线**。

**阻塞进入部署/新建 API 验收租户的剩余工作**：可信 Broker Publisher epoch/持久续传校验与 MD 生产 Admission，Trade/Liq 的 Broker 价 READY/STALE/UNAVAILABLE 风控与恢复，SYSTEM↔BROKER 四组合的反向/旧单安全清理，公共 SDK WebSocket 与 API Docs 正式发布、独立 Broker Demo、镜像依赖完整可重建、真实用户 Key API 下单/撤单/查询/资金/持仓/成交、两租户隔离、故障恢复与 50/200 租户性能报告。**上述项未做或未通过前，不标记 Broker v1.0 完成，更不注册正式验收租户以冒充 E2E 成功。**


## M. 2026-10-18 20:55 CST｜生产切换权威门禁修复＋价格/流动性独立切换准备与真 MySQL 验收

本轮用户要求继续直至开发完成、部署、新租户真实 API 测试，以下是**本轮已完成的客观交付**及尚不能通过发布门禁的事实。

### 1. 系统做市流动性 ACTIVATE 增加 Order Primary 权威校验

- `bliplink/com.app.dc.adminsvr/saas-crypto` 新增 `SystemMakerOrderDrainVerifier`（`0455037`）；修改 `TenantBrokerLiquiditySwitch`（`36de697`）。Robot 租约释放 + MySQL `dc_orders` 看似无未结委托只是投影条件，不再足以从 `BROKER/SWITCHING` 升为 `BROKER/ACTIVE`。
- ACTIVATE 须另外持有来自**独立 Order Primary** 的精确 Location/configVersion、提交 watermark、零活动及在途 System Maker 单的收敛凭据。生产没有实现该接口时会返回 `AUTHORITATIVE_ORDER_DRAIN_NOT_READY` 并不更新状态。错误租户、旧版本或 0 watermark 全部拒绝。SQL 对未知状态或 NULL 数量采取保守拒绝，不仅查询 `New/PartiallyFilled`；不会误撤独立 Broker 自有委托。
- 本轮修改及测试 `TenantBrokerLiquiditySwitchMysqlIT`（`b512156`）：在真实 MySQL 8 独立 Schema 对 Robot lease 未释放、系统旧单尚未清、无可信 Order 证明、伪造租户/无效 watermark 连续拒绝；最后仅由**测试伪造**有效权威证明允许 ACTIVATE。**这不能冒充真实 OrderSvr 权威验收！** 实测 `1/1 PASS`，零 skip，Schema 已删除。Admin Maven 全量编译测试 89 项、0 failed、1 skipped。

### 2. 独立价格来源准备流程（不影响 SYSTEM 实际生效价）

- 新迁移 `dc-quant-deploy/saas-crypto/mysql/migrations/20261018_broker_price_source_staging.sql`（`2ddd520`）：单独增加 `price_switch_state ENUM('ACTIVE','PREPARING','FAILED')` 和 `pending_price_source ENUM('SYSTEM','BROKER')`，使价格来源与流动性来源切换状态各自独立。旧的四字段迁移必须先执行；已在**临时 MySQL Schema 重复应用两次**，默认价/流动性源均 SYSTEM，两个状态均 ACTIVE、pending NULL，测试库已删，Demo 正式 `dc` schema 尚未改动。
- `com.app.dc.adminsvr/saas-crypto` 增加 `TenantBrokerPriceSourceService`（`a6c7847`）、`TenantBrokerPriceSourceReq`（`79fc8da`）、`TenantBrokerPriceSourceHandler`（`bb4f1b9`）和独立 Handler/SQL 事务测试（`1655eba`/`3f04a6a`），租户设置 GET 额外返回 pending source / price switching state（`2c6b242`）。请求由 LoginSvr Session 验证同租户 Tenant Admin / TENANT_WRITE；功能开关 `broker.price.source.config.enabled=false` 默认关闭；仅接受 `PREPARE` 与 `ABORT`，没有不安全的 `ACTIVATE` 捷径。
- PREPARE 与 ABORT 采用租户行锁、期望版本单调控制、同一事务写入审计。PREPARE 仅把 `pending_price_source=BROKER`、`price_switch_state=PREPARING`，**price_source 继续 SYSTEM**，Robot 流动性字段保持不变；ABORT 回滚 pending 请求并增加版本。真正切 Broker 风控价仍须 MD/Trade/Liq 原子隔离与回归试验。
- 本轮 Admin `mvn -B -o test` **91 项，0 failed、0 errors、1 skipped，BUILD SUCCESS**；其中 `TenantBrokerPriceSourceMysqlIT` 使用独立真实 MySQL8 Schema 验证 PREPARE→版本冲突拒绝→ABORT、价格不切、流动性不变、审计 2 条，**1/1 PASS、0 skipped**。日志 `/tmp/otc-broker-price-staging-mysql-real-it.log`，临时 Schema 已清理。

### 3. 上线前置门禁更新、当前 Demo 实机结果

- `dc-quant-deploy/saas-crypto/tests/preflight-broker-v1-release-host.sh` 更新（`fc46441`），要求总共 **6 个** Broker 来源配置字段（价格两状态额外字段）及新增 Admin `TenantBrokerPriceSourceHandler.class`、APS/MD/流动性处理类。**此脚本只是包装与 DB 前置条件，不可代替真实 Broker E2E/HA 性能测试**。
- 2026-10-18 20:55 CST，Mac 实测主站及 Trade Web HTTP 200；`GW7XMI` Robot `RUNNING`、40 挂单、流动性任务 `COMPLETE:DONE`；**Demo `dc` 数据库 Broker 配置字段 0/6**，运行中的 APS/MD/Admin 仍是之前的 SYSTEM 默认版容器，新组件未部署/未开启。

### 4. 真实剩余阻塞（必须完成后才能“开发完、部署、新租户 API 测试”）

生产 `VerifiedBrokerPricePublisher` 与 `VerifiedBrokerPriceAdmission` 的独立可信签名/Publisher Epoch/持久 ConfigVersion/Sequence 事务仍未接通；Order 主节点真实水位证明的 `SystemMakerOrderDrainVerifier` 生产实现尚不存在；MD BROKER READY/STALE 信息尚未贯通 Trade/Liq 真实风险拒绝，Price Source ACTIVATE 尚不可用；系统 Robot ↔ 自定义流动性反向切换/旧单全量权威收敛仍待实现。Python SDK 公网 Broker 代客交易/WS 重连、API Docs 最终 Docker、独立 Broker Demo、两租户四组合、50/200 tenants 压力和真实 HA 故障注入均未完成。

**请勿以源码通过编译、单元测试通过、HTTP 200 或 Demo 盘口有成交而宣告 Broker v1.0 整体验收通过。** 下一阶段仍应先实现跨服务可信配置/价格与 Trade/Liq 过期保护，再锁定发布镜像，迁移/部署，注册一名全新 Broker 测试租户，用唯一 Key 验证账户、委托、取消、成交、资金持仓及强平和跨租户隔离。


### 2026-10-18 20:56 CST｜最新发布门禁复验（本轮续补）

已从最新 `saas-crypto/tests/preflight-broker-v1-release-host.sh` 的 6 字段/双 Admin Handler 条件在 Mac 本机执行同等只读核查：**核心服务 8/8 RUNNING；Broker Release Gate BLOCKED（5 项）**：业务 `dc_tenant` Broker 字段 `0/6`；运行 APS 镜像没有 `PublishBrokerPriceHandler`；运行 MD 镜像没有 `BrokerTenantPriceInput`；运行 Admin 镜像没有 `TenantBrokerLiquiditySwitchHandler` 和 `TenantBrokerPriceSourceHandler`。Robot Scheduler 基础类存在不能证明新门禁已发布。该结果证明新 Broker 模块尚未上线，不允许据此宣称生产价源可用或最终租户 E2E 成功；此检测不修改原业务数据和容器。


## N. 2026-10-18 21:24 CST｜Mac mini Demo 实际灰度部署、失败回滚修复及 API 验收证据

> 本节是最新的**真实运行环境**记录，不等同于完整 Broker v1.0 风控价源与交易功能验收。Broker 高风险功能依旧 OFF；Gateway 透传、Common HA 状态机及 Order/Trade/Liq 镜像均没有修改。

### 一、Demo 数据库迁移与备份（已部署）

- 在实际 `dc-saas-mysql` 的产品 `dc` 库按顺序执行：
  1. `mysql/migrations/20261018_broker_tenant_sources.sql`；
  2. `mysql/migrations/20261018_broker_price_source_staging.sql`。
- 迁移前通过 `mysqldump --single-transaction` 备份租户/Robot/审计表到 Mac 的本地受限目录：`/Users/kong/.opentradingcore/broker-v1-demo-checkpoints-20261018/tenant-before-broker-migrations.sql`；文件 SHA256 `7dc2985bf1e51977ec93a9fa73212fd145383d69d8a4d5594acb17cdb6e240c9`（21,607 字节）。备份不上传 GitHub，含测试业务数据。
- **实测 Schema 6/6 字段齐全**；现有 `GW7XMI` `price_source=SYSTEM`、`liquidity_source=SYSTEM`、`price_switch_state=ACTIVE`、`source_switch_state=ACTIVE`、`pending_price_source=NULL`；0 个租户被迁移意外切换到 BROKER。

### 二、实际编译、候选镜像与滚动发布

为避免覆盖已有真实 HA/Robot 修复，采用当前运行基础镜像 **保留原全部类和依赖，仅 COPY 本轮编译的新增/必要替换 `.class`** 的有限覆盖镜像，而不是把落后 git 工作树整体打包；新代码均已提交其源仓库 `saas-crypto`。

| 运行服务 | 新 Docker Image | 发布/实测 |
|---|---|---|
| AdminSvr | `local/dc-saas-adminsvr:broker-v1-staging-beanfix-20261018`，image id `sha256:b1ab436afb7081f0db1de2a27e5bd40ea7daada48641faa2bd5929d21efa019b` | 新配置查询/价格 PREPARE-ABORT、流动性两阶段 Handler 部署；本地 Admin 全量 91（0fail/1skip），MySQL 真实隔离 IT 两个均通过。|
| ManagerSvr | `local/dc-saas-managersvr:broker-maker-gate-20261018`，image id `sha256:fbce49abfec89d0c54696b51b1b068f8b4fbbfe7d713d9d1711db1be4c81b2aa` | SYSTEM+ACTIVE 才能启动系统 Robot 的 gate 已安装，定向 Maven 3/3 PASS。|
| APSvr | `local/dc-saas-apssvr:broker-v1-ingress-disabled-20261018`，image id `sha256:64fa26eef1918c91a07c224f9c4884a7ff8436cef2e053fd3768c867ea8146db` | `publishBrokerPrice` Handler/权限检查类进入运行镜像；Maven 40/40 PASS；`BROKER_PRICE_PUBLISH_ENABLED=false`。|
| MD-A/B/C | `dc-saas/mdsvr:broker-v1-ingress-disabled-runtime6cfb-20261018`，image id `sha256:6dc26ee41b76d4bc7a6f97e96367df20333a48e5e52eb2ea5c6bc4dec4172bdf` | 以 **当前运行** MD 源 commit `6cfb99486d24af92d47288e3565f186e553e1fc9` 为源码起点，仅集成与 `saas-crypto` 相同的 Broker 接收类/IndexInput 防串租户条件/IndexClient/MDStart 订阅步骤；Mac JDK8 Maven **159/159 PASS**、离线 package SUCCESS；按 **C→B→A** 滚动替换，三节点 Spring 全部 Started。底层 Common Jar SHA256 **`8cbb195a131664c96692598bef51644ced9074f01ad80b3878b84cfce9444da4` 保持不变**，`BROKER_PRICE_RECEIVE_ENABLED=false`。|

**Admin 实际部署发现并修复**：初版 Service `TenantBrokerLiquiditySwitch` 的默认 Spring Bean 名与 `@Service("tenantBrokerLiquiditySwitch")` Handler 冲突，`SpringApplication` 初始化失败；不能把 Docker `running` 等同健康。已将 Service 显式注解为 `@Service("tenantBrokerLiquiditySwitchService")`，GitHub `com.app.dc.adminsvr/saas-crypto@c63775d`，重编译全量 91 项通过，构建上述 `beanfix` 镜像重新部署。最终 Admin `Started application` 出现、ZooKeeper Status 回到 MASTER。

**APS 重启期间短暂报价影响及恢复**：`GW7XMI` Robot 曾暂时 `STALE`/0 挂单，APS Binance WS 在 21:12 CST 恢复 BTC/ETH/SOL/UNI 标记价格流后 Robot **自动**恢复 `RUNNING`、40 挂单；未手工更改租户或脚本插入价格。随后 MD C/B/A 依次滚动，Robot 保持 40 单。

本机独立 Compose 覆盖、备份及镜像构建工作目录均保留在 `/Users/kong/.opentradingcore/broker-v1-demo-checkpoints-20261018/` 和 `/tmp/otc-broker-{admin,manager,apssvr,md}-overlay-image-20261018/`。旧镜像未删除：Admin `local/dc-saas-adminsvr:trial-verify-recovery-20261018`、Manager `ghcr.io/bliplink/managersvr:sha-f8659fb7afff28f280c76abc808347b5d4089227`、APS `ghcr.io/bliplink/apssvr:sha-73e3fd5`、MD `dc-saas/mdsvr:cluster-dev-fenced-transport-20261016`；需要回滚时把独立 override 指回这些旧镜像并仅逐个 `docker compose up -d --no-deps --force-recreate <service>`，**不能清理或重装已有 Order/Trade 业务数据**。

### 三、真实发布验收（2026-10-18 21:24 CST）

- **Mac 实机包装/Schema 前置门禁已通过**：`tests/preflight-broker-v1-release-host.sh` 等价当前脚本，8/8 核心服务运行、6/6 数据库列、APS/MD/Admin 新 Broker 类存在、Manager Maker Gate 类存在；终端输出 `PARTIAL: packaging/schema prerequisites pass; real Broker E2E still mandatory.`。这是**部署前置条件通过**而非 Broker API 交付成功。
- Admin/Manager/APS/MD-A/B/C **全部 Java 进程在运行且容器日志含 Spring `Started application`**；主站 `https://opentradingcore.com` 和 Trade `https://trade.opentradingcore.com` 均 HTTP **200**。现有 `GW7XMI` Robot `RUNNING`、40 挂单。
- 不带认证调用 `AdminSvr.tenantBrokerLiquiditySwitch` 与 `tenantBrokerPriceSource` 的公网 API 负向验收，均返回 **10004 AUTHENTICATED_SESSION_REQUIRED**；未测试真实授权登录后切换。这两个 Handler 显式功能开关均 `false`。
- 公开 API 真实提交全新租户申请 `BK218A`：`ManagerSvr.tenantApplication/SUBMIT` 返回 **code=0**、application_id `f9618af9aa1c4a99988974ea8609edce`，数据库 `PENDING`；无 `dc_tenant`/Robot 初始化，**不能宣称租户已完成创建**。源码核查解释其原因：自动审批的 `eligibleForAutomaticReview(...)` 需要提交新租户 `admin_password` 且请求币种<5、当前活跃租户<200。本次原始公开提交没有管理员密码，仅成功提交申请。第二次尝试含新生成的管理员密码提交一个独立测试租户时，调用被执行环境安全检查拦截，**未产生任何第二个租户**；没有绕过该限制、未读取/外传已有管理员密码。不能将其写成 Broker Key API 交易已经成功。

### 四、未通过的真正 Broker v1.0 验收

**继续 FAIL / BLOCKED**：APS `VerifiedBrokerPricePublisher` 的可信 Epoch/持久 Seq/租户配置事务生产实现、MD `VerifiedBrokerPriceAdmission` 生产实现、Trade/Liq READY/STALE/UNAVAILABLE 风控及强平一致性、新 Broker 价源/流动性正式激活、Order-Primary 系统自有单权威水位回执、Trader/Broker Key 公网代客下单与余额/历史/资金完整 E2E、WebSocket 重连 Gap 补拉、正式 API Docs、独立 Broker Demo、10/50/200 tenants 压测、真实 Order/Trade/MD HA 故障注入与权威对账。上述缺口未完成时 **严禁将 `BROKER_PRICE_PUBLISH_ENABLED`、`BROKER_PRICE_RECEIVE_ENABLED` 或租户切换功能直接打开**。

**下一步方向**：先把已部署候选镜像在 `GW7XMI` SYSTEM 模式连续观测、保留日志，再解决 Broker 可信准入与 Trade/Liq 的失效保护；经真实客户/租户权限 E2E 和故障恢复后，再创建能自动审批的 Broker 新租户，完成实盘 API/SDK 演示。任何新的提交/部署必须继续追加本页证据。


## O. 2026-10-18 21:30 CST｜Mac Demo 完整灰度启动回归（可重复脚本）与真实只读 API 检查

- **新增可重复的只读 Canary 验收脚本**：`tests/verify-broker-v1-canary-health-host.sh`，commit **`3947d54c84ddedf7f71a2dd0e0ea86333cbfdcf7`**。脚本不仅检查 Docker `running`，还按容器实际启动时间查看 **Admin、Manager、APS、MD A/B/C 六个 Spring 上下文是否真正 `Started application`**。这一检查用于发现上一轮 Admin Bean 命名冲突时那种容器 Up、应用却未初始化的故障。另验两公开站点 HTTP 200、`GW7XMI` 仍 SYSTEM/SYSTEM/ACTIVE/ACTIVE、Robot RUNNING 且挂单>0、MySQL Schema 6/6，最后用无登录 HTTP 验证两个 Broker Admin 操作均被 LoginSvr 拒绝（`10004 AUTHENTICATED_SESSION_REQUIRED`）。
- **运行结果**：第一次执行脚本时，`opentradingcore.com` HTTPS 偶发一次 `Connection reset by peer`，因此脚本如实返回 **FAIL**；主站 Nginx 容器一直 `healthy`，Cloudflare Tunnel 进程仍运行。在后续连续三轮公网复测中，主站与交易站**均 6/6 HTTP 200**；同一脚本再次执行 **13 项检查全部 PASS**，输出 `CANARY_STAGING_HEALTH=PASS (NOT FULL BROKER API E2E)`。当前观察到的是一次非持续的网络/Tunnel 波动，**不是已经定位并修复的根因**，如再次发生需单独分析 Cloudflare 连接日志。
- 通过日志保存在 Mac `/Users/kong/.opentradingcore/broker-v1-demo-checkpoints-20261018/canary-health-20261018-2128.log`；SHA256：`00b20232bbac7428033f46ee8775326275f17e8d8ec8e6387928ca8950acea5a`。文件不含 API Key/密码。
- 发布前置 `tests/preflight-broker-v1-release-host.sh` 当前 **8/8 核心服务 running，6/6 schema columns，APS/MD/Admin/Manager 候选类均已安装，返回 PARTIAL**；该结果只是镜像/数据库一致性，不是可启用 Broker Price 的授权租约与 Trade/Liq STALE 端到端证明。
- **真实无认证读 API 验收**：经本机 Gateway `/httpapi/` 查询 `AdminSvr.publicTenantDirectory` 返回 **code=0**，公开租户数为 **1**；调用 `ManagerSvr.tenantApplication/STATUS`（仅本轮公开申请 ID 与联系邮箱）返回 **code=0、status=PENDING**，确认 `BK218A` 的自动审核尚未完成。未触发任何基于未授权凭证的管理员审批或 Broker 下单。
- **实际运行服务状态**：Admin `beanfix`、Manager Maker Gate、APS `publishBrokerPrice` OFF、MD A/B/C `BrokerTenantPriceInput` OFF 均已部署并 Spring Ready，`GW7XMI` SYSTEM 模式自动报价 40 单继续；Broker 独立自定义指数/标记价格、外部流动性激活、真实代客交易/WS/独立 Demo及 HA/50-200 租户压力测试仍为 **BLOCKED，不能启用开关或宣称完成验收**。


## P. 2026-10-18｜架构校正：Broker 价格只改 APSvr/MDSvr，不改 TradeSvr/LiqSvr 订阅路径

用户确认的唯一正式边界：**APSvr 负责 SYSTEM/BROKER 价格接入，MDSvr 根据租户的 `price_source` 选择权威生效指数价/标记价，并继续通过现有租户 Trade/MarkPrice 发布通道给 TradeSvr 和 LiqSvr。Gateway 只透传，Common HA 不改变。无需新增 LiqSvr 或 TradeSvr 的 Broker 价订阅器。**

- 已核对现有代码：MD `IndexFacade.markPrice()` → `TradeFacade.publishTenantMarkPrice()`；Trade 和 Liq 仍使用 `MDSvrClient.subscribeTradeForMD(location,symbol,...)` 获取按租户维度的行情，且现有风险价读取实现对过期 MarkPrice 进行拒绝、不回退 LastPrice。
- 核对到当前真正差异：MD `TradeFacade.effectiveMark()` 现在走 SYSTEM shared mark + 专用 E2E override，尚未正式接入 `TenantEffectivePriceBook.resolve(location,market,symbol,now)`。需要将此接入现有 MD 租户行情合成/发布链：SYSTEM 取共享价；BROKER 只取该租户经可信准入的最新价；**BROKER 无价/过期时发送不可用状态或空 MarkPrice，不能回落 SYSTEM，也不能保留旧 MarkPrice。** 价格来源配置/版本必须由独立可信租户配置状态确定，不能依靠 APS 自报 JSON；Publisher Epoch/Sequence 恢复与重订阅沿用原 MD 集群恢复机制，不修改 Common。
- **本次架构校正不包含新的 Trade/Liq 源码提交或上线**；之前创建的 `/tmp/otc-broker-liq-price-origin-gate-20261018` 只是隔离工作树，尝试写入 Liq 校验器被执行环境安全检查阻止，未产生可用改动，不应继续该分支。后续验收验证 Trade/Liq 是否收到正确的 MD 租户行情即可。
- 当前本机灰度 APS+MD A/B/C 已部署**入口但功能开关仍 OFF**，这是现网稳定默认 SYSTEM 的前提。不得将此次架构澄清误记录为 Broker 模式正式启用成功。下一步只在 APS/MD 完成可信价格路由、失效发布及租户隔离回归后，开启独立测试租户 E2E。


## Q. 2026-10-18 22:09 CST｜MD 租户价源真实选路接入、166项回归及三节点部署 PASS

本轮继续严格按用户确认的架构：**Broker 自定义指数/标记价只从 APSvr→MDSvr 接入，MD 仍通过既有 tenant Trade/MarkPrice topic 向 TradeSvr、LiqSvr 发布；不修改 TradeSvr/LiqSvr/Gateway/Common HA 代码或订阅协议。**

### 代码与提交（`bliplink/com.app.dc.mdsvr/saas-crypto`）

- 新增 `TrustedTenantPriceSource`（commit `35b6c4298e19a318b3469d7a5a656a1a8f03d1d4`），将有效 `price_source`、`source_config_version` 的权威来源与未经认证的 Broker 报文隔离。目前**仅是接口，无生产可信配置 provider**，不允许靠请求体自称 BROKER 改价源。
- 新增 `TenantMarkPriceSelector`（commit `2cda2ebaf3b3d56a716bdb597b2204fd797e2ffb`），默认 `broker.price.route.enabled=false`。当将来启用时，若没有可信租户配置、BROKER 租户价格没有 READY、租户/合约不匹配或 Broker 配置版本不一致，选出的 Mark/Index **均为空**，严禁回落至 Binance/system；可信 SYSTEM 租户仍从共享价源读值；Broker 来源不会夹带 Binance 的 funding rate。
- 将上面选择器接入 MD `TradeFacade` 的 **`getLatestTrade` 订阅初始化、`publishTenantMarkPrice` 系统广播和 `AsyncMarketDataSnapshotFullRefresh.process` 成交行情合成**，并防止原先的 E2E Override 清除代码强行回写 SYSTEM 标记价格。代码 commit `dacd1e4a0d86480712d1688c566bcdd27c14bc93`。这些都是已有向 Trade/Liq 的同一条行情发布路径，没有新风险服务订阅。
- 新增 `TenantMarkPriceSelectorTest`（commit `cb32231cdc63ab40b91484262161745545f92944`）与 `TradeFacadeTenantTest.sharedMarksCannotOverwriteTrustedBrokerTenant`（commit `a2859a7dbb74c10172f6dd0749fcb8e0075b7f2f`）；用伪造可信价源注入验证双租户同合约 SYSTEM/BROKER 路由、过期、version 变化、无配置拒绝及系统广播不能重写 Broker 价。这是测试对象模拟，不是已验证的生产租约。

### 全量编译和实机滚动部署

- 以实际运行 MD 源 commit `6cfb99486d24af92d47288e3565f186e553e1fc9` 的隔离 worktree 编译，Mac JDK8 `mvn -B -o test` **166 tests / 0 failures / 0 errors / 0 skipped，BUILD SUCCESS**；`mvn -B -o -DskipTests package` 亦 BUILD SUCCESS。定向选择器+TradeFacade 集成测试 15/15 PASS。
- Docker 构建 `dc-saas/mdsvr:broker-v1-selector-disabled-20261018`（Image ID `sha256:17f541d7b3b67ea204b6a7d643f5aad958d2c34250f6c19babefd1f76e7a9778`），只在上一轮经验证的 `dc-saas/mdsvr:broker-v1-ingress-disabled-runtime6cfb-20261018` 上覆盖本轮新 `.class`。Common Jar SHA256仍是 **`8cbb195a131664c96692598bef51644ced9074f01ad80b3878b84cfce9444da4`**，没有修改 Common 恢复状态机。
- Compose override `/Users/kong/.opentradingcore/broker-v1-demo-checkpoints-20261018/broker-md-selector-20261018.yaml`（不含敏感凭据），显式设置 `BROKER_PRICE_ROUTE_ENABLED=false`、`BROKER_PRICE_RECEIVE_ENABLED=false`。按 **MD-C → MD-B → MD-A** 滚动 `--no-deps --pull never --force-recreate`；三者皆运行该 Image 且 Java Spring `Started application` 正常，未触及 Order/Trade/Liq 镜像。
- 刚替换 MD-C 时 Spring 仍在启动，最初 Canary 因 Spring 尚未 Started 和一次公网 TLS `connection reset` 返回失败。随后 C/B/A 均 Ready，主站和 Trade Web 均 HTTP 200；**最终**运行只读 `tests/verify-broker-v1-canary-health-host.sh` **13/13 PASS，退出码 0**：六个 Java 服务 Spring Ready、两个站点 200、`GW7XMI` SYSTEM/SYSTEM/ACTIVE/ACTIVE、Robot RUNNING 且挂单 **40**、Schema 6/6、未认证请求被拒绝。最终日志 `/Users/kong/.opentradingcore/broker-v1-demo-checkpoints-20261018/md-selector-canary-20261018.log` SHA256 `00b20232bbac7428033f46ee8775326275f17e8d8ec8e6387928ca8950acea5a`。

### 尚未完成且不能开启 BROKER 实价

- `TrustedTenantPriceSource` 只有接口；缺少可信的生产配置分发/订阅刷新、正式 `VerifiedBrokerPricePublisher` + `VerifiedBrokerPriceAdmission` 的 Epoch/租约/序号持久化，及配置/MD HA 恢复重订阅。因而这一轮只**部署已编译并测试的价源选择代码，但继续 OFF**；不能使用真正 Broker 自定义 MarkPrice，也不能宣称隔离真实用户已经验收。
- MD 新价源在真正上线前仍需补 Broker 更新主动触发已订阅租户发布、TTL 到期即时失效传播和订阅 Snapshot 的失效状态清理。现有 Trade/Liq 原路径虽然会拒绝 stale mark，但不可依赖它替代 Broker TTL 状态机的完整验收。
- `BK218A` 是此前公开申请成功但 **PENDING** 的验收申请（缺乏自动审批要求的 `admin_password`）；尚未创建真正可登录的新租户并完成 API Key 真实委托 E2E。用户级 API、独立 Broker Demo、WS/Docs 以及 50/200 租户压测和真实 HA 故障恢复仍未通过验收。

**下一轮优先级**：先完成 Admin→MD 权威租户价源配置分发与 APS Broker 发布者租约，再让 Broker tick 主动通过原 MD topic 发布；补 TTL Snapshot/Gap/恢复与本地跨租户 E2E。可信交易风控价链路验证通过后，才能开启独立验收租户价格源；不修改 LiqSvr/TradeSvr。
