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
