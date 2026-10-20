# OpenTradingCore 自定义产品 + Python API 交付、验收与 GitHub 分支汇总

> 交付日期：2026-10-20；目标分支采用各仓库现有的 `bliplink/*` origin。
> 本文是本轮业务交付的统一入口，不代表独立 Common/Trade HA 开发已经完成。
> GitHub 交付分支为**独立代码快照与后续合并入口**，未直接更新远程 `saas-crypto`。

## 一、交付目标与业务约定

- 租户自主创建交易产品，创建时直接建立租户作用域 `dc_symbol` 产品规则及租户产品绑定；**不需要额外 ACTIVATE**。
- 服务识别租户交易产品使用 `location + security_id`；只有租户已启用的产品进入交易业务，停用产品不对匿名列表／盘口暴露。
- 产品代码与行情数据源代码完全独立，例如 `BTC003USDT` 可以绑定 `CUSTOM_BTC`。
- **一个产品只有一个当前数据源**。租户主动切换 BIND 后立即改用新的当前源；旧源不自动回退、不同时生效。
- APS 可由已认证 Broker/TenantAPI 为**自身租户的数据源**发布指数价、标记价；MD 对应租户路由，超过 TTL 便不再采用价格。**不设置切换时 1% 价格偏差门槛**。
- Trader API Key 代表本人交易员；Broker API Key 按授权代客交易，两者的身份与权限不能混用。普通 Broker Key 不开放租户管理和客户模拟资金权限。
- 对外 API Docs 保持单页分类、中英文版本；主站、Trade Web、租户 Web、文档通过统一语言偏好保持一致。

## 二、已完成的研发与实测结果

### 自定义产品、数据源和交易

1. AdminSvr：租户源管理、产品源绑定、租户 `dc_symbol` 规则写入、开启/停用隔离、公开租户产品查询；数据库产品展示名已扩到 `VARCHAR(128)`。
2. APS/MD：自定义源与产品解耦、Broker 签名价格发布、当前源绑定生效、TTL 失效、旧源行情撤销和匿名盘口只显示启用产品；不存在自动备用源。
3. Gateway：公开的 `AdminSvr.querySymbol` 必须包含租户 location，匿名管理接口仍拒绝访问；全局管理接口未公开。
4. Order/Trade：产品租户识别及启用检查；Order 的 Common `AsyncSingleSeqThreadGroup` 修复同 Key 首次创建时多个 Worker 的竞态。
5. Order 修复对照：原部署 Common 3.0.22 实测同 Key 16 并发可能执行 16 个回调；修复后连续八轮同 Key 最大并行数为 1。独立 Common 8/8 JUnit 通过，包括 10,000 条消息不丢不重、不同 Key 并行、死 Worker 剩余队列恢复。
6. 已在 Demo **滚动替换 Order A/B/C**：`local/dc-saas-ordersvr:single-key-queue-b0be90c-20261020`，原 Common JAR 的 HA/WAL/Snapshot 部分保持不变。
7. Demo 新租户真实交易：`ESPONL` 标准 Maker/Taker；`KFAOUW` 和 `K4OB59` 两次近同时相反方向订单，客户端请求启动间隔分别约 **0.351 ms / 0.318 ms**。三组 `BTC003USDT` 买卖订单均各 2/2 `Filled`，执行记录、开仓余额/持仓查询通过，没有重复成交 ID 或交叉 `New` 挂单残留。**这不等于已进行 Trade/Common HA 或 200 租户压测**。

### Python API SDK 0.1.4

- Python Trader：签名登录、下单/撤单、订单与成交历史、余额/持仓、杠杆及持仓模式、最多 50 个显式 OrderID 批量撤单；`ReduceOnly` 平仓参数严格校验。
- Python Broker：签名登录、租户自定义指数价/标记价发布、已授权客户的代客下单/撤单/查询以及批量撤单；强制作用域与业务权限检查。
- **匿名 `PublicMarketClient`**：只需 Gateway URL + 租户 location 就能 `products()` 列出启用产品、`snapshot(symbol)` 读取当前行情，无须假造 API Key。
- `wait_for_product()` 和 `wait_for_order_ready()` 只读轮询新产品目录同步，不自动重试结果不明确的订单写操作。
- WebSocket `GatewayWebSocket`：真实 `wss://trade.opentradingcore.com/gateway` 二进制 GZIP 协议适配，已验证公开匿名 CONNECT 返回 `code=0`、订阅 ACK `Code=0000`、心跳 `cmd=2` 收到应答。尚未验证真实私有交易员 WebSocket 订单推送和断线增量追平。
- SDK **32/32 Python 单元测试**通过；OpenAPI 17 个方法请求结构通过，16 个方法外部单页展示；英文及中文 MkDocs 严格构建通过。
- 已提供 `demo_trader_api.py`、`demo_broker_api.py`、`demo_custom_price.py`、`demo_public_websocket.py` 等示例，写操作必须显式请求。
- 文档及 SDK Demo 镜像为 `local/dc-saas-api-docs:sdk-014-20261020`，已健康部署。Wheel 与源码 ZIP 的外部 HTTP 下载返回 200；改用新版本号避免旧 0.1.3 ZIP 被 Cloudflare 命中缓存。

下载入口：

- 文档：https://api.opentradingcore.com/
- Wheel：https://api.opentradingcore.com/sdk/opentradingcore-0.1.4-py3-none-any.whl
- SDK 源码及示例：https://api.opentradingcore.com/sdk/opentradingcore-python-sdk-0.1.4.zip

## 三、GitHub 交付仓库与独立分支

以下是**已使用非强制 `git push` 成功发布**的源代码分支（不会覆盖正式 `saas-crypto`）。本部署仓库的汇总分支见末行。

| 组件 / 仓库 | GitHub 交付分支 | 本地源提交 | 内容 |
| --- | --- | --- | --- |
| API Docs / SDK — [bliplink/opentradingcore-api-docs](https://github.com/bliplink/opentradingcore-api-docs) | `codex/custom-product-python-sdk-20261020` | `bcf9627` | SDK 0.1.4、OpenAPI、中英文单页、公开 WSS 及示例 |
| Common — [bliplink/com.app.common](https://github.com/bliplink/com.app.common) | `codex/common-single-key-queue-20261020` | `b0be90c` | 按 Key 原子创建 Worker／入队、恢复队列、JUnit；之后 cherry-pick 到 HA 分支 |
| Order — [bliplink/com.app.dc.ordersvr](https://github.com/bliplink/com.app.dc.ordersvr) | `codex/order-near-simultaneous-qa-20261020` | `a136b2c` | 启用租户产品校验、双订单并发准入回归 |
| Order（行情目录）— 同上 | `codex/order-tenant-catalog-refresh-20261020` | `7d95cf7` | 避免 querySymbol 完整镜像漏掉已停用租户产品 |
| AdminSvr — [bliplink/com.app.dc.adminsvr](https://github.com/bliplink/com.app.dc.adminsvr) | `codex/admin-tenant-products-20261020` | `7dc036c` | 租户自定义产品、唯一当前数据源、规则及列表查询 |
| MDSvr — [bliplink/com.app.dc.mdsvr](https://github.com/bliplink/com.app.dc.mdsvr) | `codex/md-current-price-source-20261020` | `a7296e3` | BIND 切换、TTL 校验、停用产品过滤 |
| APSSvr — [bliplink/com.app.dc.apssvr](https://github.com/bliplink/com.app.dc.apssvr) | `codex/aps-broker-custom-price-20261020` | `3d3062e` | Broker 指定自身租户数据源发布价格 |
| Gateway — [bliplink/gw](https://github.com/bliplink/gw) | `codex/gateway-public-tenant-products-20261020` | `9a33a3c` | 匿名租户产品公开方法白名单及路由 |
| Main Web — [bliplink/opentradingcore-web](https://github.com/bliplink/opentradingcore-web) | `codex/main-web-shared-language-20261020` | `7cecffa` | 跨子域共享语言首选项 |
| Trade Web — [bliplink/dc-trade-web](https://github.com/bliplink/dc-trade-web) | `codex/trade-web-shared-language-20261020` | `0ee2d30` | 交易核心语言同步 |
| Tenant Web — [bliplink/dc-saas-tenant-web](https://github.com/bliplink/dc-saas-tenant-web) | `codex/tenant-web-shared-language-20261020` | `402b4ba` | 租户后台语言同步、现有价源操作 UI |
| Trade（仅产品业务提交）— [bliplink/com.app.dc.tradesvr](https://github.com/bliplink/com.app.dc.tradesvr) | `codex/trade-tenant-products-only-20261020` | `ad68436` | 租户启用产品识别；**不携带后续的 Trade HA 测试提交** |
| 部署/验收汇总 — [bliplink/dc-quant-deploy](https://github.com/bliplink/dc-quant-deploy) | `codex/custom-product-api-sdk-delivery-20261020` | 本文所在交付分支 HEAD | Compose 覆写、业务实测、测试脚本、数据库迁移、本总结及合并说明 |

常用分支链接示例：

- https://github.com/bliplink/opentradingcore-api-docs/tree/codex/custom-product-python-sdk-20261020
- https://github.com/bliplink/com.app.common/tree/codex/common-single-key-queue-20261020
- https://github.com/bliplink/dc-quant-deploy/tree/codex/custom-product-api-sdk-delivery-20261020

## 四、未完成及需明确分离的验收

| 优先级 | 事项 | 实际状态 / 下一步 |
| --- | --- | --- |
| P0 | 两个 Trader API Key 签名交易闭环 | Python SDK 签名登录已实测一把测试 Key，但两把 Key 真正执行下单、撤单、订单历史、ReduceOnly 平仓以及资金/盈亏对账 **未完成**；不能把 WEB session 的成交冒充 Key 验收 |
| P0 | Broker 代客下单/撤单 | Broker 签名登录 + 自定义价格发布成功；委托写入、撤单及跨租户拒绝完整业务流尚未实测通过 |
| P0 | Cloudflare HTTP 403/1010 | `https://trade.opentradingcore.com/api` 与 `/httpapi/` 的部分 Python 请求在 Cloudflare 边缘被 403/1010 拒绝；本地 HTTP 200、正式 WSS 正常。需在 Cloudflare Security Events 确认并调整合法 API 客户端对应 WAF 规则；不得关闭 Gateway 的 HMAC、租户鉴权 |
| P1 | 新产品目录短暂 `5004` | Admin 已生效后 Order 目录仍可能延迟；SDK 新增只读等待，但尚未从后端消除异步传播窗口 |
| P1 | WebSocket 私有事件 | 公开握手、订阅 ACK、心跳已验证；真实成交推送、断线重连快照与 diff gap 尚未验收 |
| P1 | Common/Trade HA 合并 | 另一 Codex 会话独立开发集群。应将 `b0be90c` cherry-pick 到最终 Common HA 分支，统一 Common Jar 与 Order/Trade 镜像后重新跑业务及 HA 验收；**不要用本交付分支整体覆盖 HA 分支** |
| 后续 | 多租户压力及持续负载 | 两轮近同时成交成功不等于 50/200 租户 steady-load 或 HA SIGKILL 验收通过 |

## 五、合并策略、部署原则与安全说明

1. **源代码先独立合并并解决冲突**。`dc-quant-deploy` 本地 `saas-crypto` 在本次交付时相对 `origin/saas-crypto` 为 **ahead 78 / behind 625**（仅反映总结提交之前的工作区）；不能强推/直接快速合并到远程。应逐仓库审核交付分支和当前主分支差异、按功能 cherry-pick/PR 合并。
2. Common 队列补丁 `b0be90c` 只保证本进程同 Key 队列的唯一 Worker，不代替持久化、HA 恢复和 WAL 正确性。当前 Demo Order 镜像只覆盖修复队列类，**不是正式发布的统一 Common Maven 版本**。
3. 客户申请/模拟资金经租户 Web 或明确授权的 WEB 流程；普通 Broker Key 必须继续受 `ORDER_READ`/`ORDER_WRITE` 等权限约束，不能给普通 Key 偷加 `CUSTOMER_CASH` 或 `TENANT_WRITE`。
4. 每次新镜像替换按独立服务滚动，保留现有 Demo 租户数据。源代码分支发布与 Docker Demo 上线是两条独立操作，GitHub 推送不等于 GHCR 构建。
5. **未使用 GitHub Actions**、未运行线上真实资金转账、未清除 Demo 数据、未访问 Mac Documents/`文稿`，未执行 Trade/Common HA 故障注入。构建临时目录（`target`、`.stage-*`、`.build-deps`、SDK 临时凭据）不应进入 Git 提交。
6. 工作区中还有其他历史会话的未提交修改，本次只提交本文件；其他任务未被擅自 add/reset/rebase。

## 六、已有详细验收记录索引

- `docs/CUSTOM_PRODUCT_PYTHON_API_SDK_014_ACCEPTANCE_20261020.md`
- `docs/ORDER_SINGLE_KEY_QUEUE_DEMO_ACCEPTANCE_20261020.md`
- `docs/COMMON_PER_KEY_QUEUE_FIX_HANDOFF_20261020.md`
- `docs/API_DOCS_SHARED_LANGUAGE_ACCEPTANCE_20261020.md`
- `docs/CUSTOM_TENANT_PRICE_TRADER_ACCEPTANCE_20261020.md`
- `docs/MD_SOURCE_BIND_MARK_REFRESH_20261020.md`

**下一步优先级：先修复 Cloudflare API 路径对标准 Python 客户端的 403/1010，再做 Trader/Broker 真正签名交易闭环（含撤单/ReduceOnly/PnL），之后验证私有 WSS 消息和 Common HA 最终合并。**
