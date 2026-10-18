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
