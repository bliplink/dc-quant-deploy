# DC Core Architecture 基线与后续会话交接说明

> **用途**：这是 `dc-quant-deploy` 的系统架构基线。任何新的 ChatGPT / Codex / WebCodex 会话，在继续开发、部署、验收、压测、排障之前，**必须先阅读本文件**。  
> **目标**：防止因为会话切换而误解服务职责、数据流、HA 模型、API 边界或当前阶段，导致重复开发、改错服务、错误重启、错误验收。  
> **当前主线**：`saas-crypto`  
> **最后更新**：2026-09-28

---

## 1. 系统最终目标

本系统不是单一交易页面，也不是单租户撮合 Demo，而是一套可对外提供服务的 **多租户交易核心平台**。

总体目标：

1. **多租户 SaaS 交易核心**
   - 平台可以创建和管理多个独立租户 / Broker。
   - 每个租户以 `location` 为核心隔离边界。
   - Broker 与 Broker 之间资金、账户、订单、持仓、行情配置、机器人配置彼此独立。
   - 支持两类 Broker：
     - 使用本平台 Web / location / 内置能力的 Broker；
     - 自建后端，通过 Broker API 接入本交易核心的 Broker。

2. **统一交易核心，可扩展多资产**
   - 当前第一阶段按 Crypto 完善。
   - 架构必须可继续扩展到 FX、商品、债券及自定义交易品种。
   - MarketIndicator / SecurityID / Location 等维度不能写死为加密货币专用逻辑。

3. **完整交易链路**
   - Login / Account
   - 下单 / 撤单 / 批量撤单
   - OrderSvr
   - TradeSvr
   - 撮合 / 风控 / 资金 / 持仓
   - Projection
   - Market Data
   - Robot liquidity
   - Kline / Trade history
   - Web / OpenAPI / WebSocket

4. **高可用核心**
   - 核心 HA 服务：**OrderSvr、TradeSvr、MDSvr、LiqSvr**。
   - 分区、主备、恢复、快照、journal、readiness、failover 必须以“业务不中断 / 数据不丢 / 可验证”为目标设计。
   - 不能把“容器活着”当作 HA 成功，必须验证 partition assignment、READY、replication、watermark、snapshot/journal 一致性。

5. **高性能**
   - 下单链路不允许人为 200ms 延迟。
   - Robot 盘口不允许明显延迟。
   - 首单冷启动需要消除。
   - 单热点盘口不能因为 1000 级压力就出现分钟级积压、假成功、不可查询或服务长期 PARTITION_NOT_READY。
   - 行情历史目标支持上亿 ticker / trade / kline 数据，并做到秒级查询。

6. **统一入口**
   - GW 是统一 HTTP + WebSocket 入口。
   - 外部客户端不应知道 OrderSvr / TradeSvr / MDSvr 的物理拓扑。
   - GW 做协议、路由、连接、聚合入口；**GW 不承载交易业务逻辑**。

---

## 2. 总体架构

```mermaid
flowchart LR
    U1[Trader Web / Mobile]
    U2[Tenant Web]
    U3[Platform Admin Web]
    U4[Broker / Trader / Tenant API Client]

    GW[GW\nUnified HTTP + WebSocket Gateway]
    LOGIN[LoginSvr]
    ADMIN[AdminSvr]
    MANAGER[ManagerSvr]

    ORDERA[OrderSvr A]
    ORDERB[OrderSvr B]
    TRADEA[TradeSvr A]
    TRADEB[TradeSvr B]
    MD[MDSvr Cluster]
    LIQ[LiqSvr]
    PROJ[ProjectionSvr]
    ROBOT[RobotSvr]
    APS[APSSvr\nExternal Market Adapter]

    MYSQL[(MySQL)]
    CK[(ClickHouse)]
    ZK[(ZooKeeper)]
    BINANCE[Binance / External Market]

    U1 --> GW
    U2 --> GW
    U3 --> GW
    U4 --> GW

    GW --> LOGIN
    GW --> ADMIN
    GW --> MANAGER
    GW --> ORDERA
    GW --> ORDERB
    GW --> TRADEA
    GW --> TRADEB
    GW --> MD

    ORDERA <--> ORDERB
    TRADEA <--> TRADEB

    ORDERA --> PROJ
    ORDERB --> PROJ
    TRADEA --> PROJ
    TRADEB --> PROJ

    PROJ --> MYSQL

    MD --> CK
    ADMIN --> CK

    LIQ --> GW
    ROBOT --> GW

    BINANCE --> APS
    APS --> GW
    GW --> ROBOT
    GW --> MD

    ORDERA --> ZK
    ORDERB --> ZK
    TRADEA --> ZK
    TRADEB --> ZK
    GW --> ZK
```

---

## 3. 服务职责边界

### 3.1 GW

GW 是统一网关，不是业务服务。

职责：

- HTTP API 入口；
- WebSocket 长连接入口；
- 逻辑服务名到物理服务实例的路由；
- Order / Trade 分区路由；
- 服务预连接；
- 行情订阅 fanout；
- OpenAPI 的统一入口层。

禁止：

- 不把撮合、资金、持仓、强平、订单状态机等业务逻辑塞进 GW。
- 不让 Web 直接依赖 MDSvr / OrderSvr / TradeSvr 物理地址。

GW 配置必须提前声明核心 RequestService，使 GW 启动后可以预连接 A/B 实例，避免首单因为物理连接未 Online 触发多次退避。

---

### 3.2 OrderSvr

OrderSvr 是订单状态机和订单撮合入口。

主要职责：

- 接收 New / Cancel / CancelAll / Replace 等订单指令；
- 订单幂等；
- OrderID / ClOrdID 处理；
- 订单 book；
- 订单生命周期；
- 与 TradeSvr 进行风控 / 资金 / 持仓协作；
- 订单状态 journal；
- Order cluster partition / primary / replica / readiness / recovery。

重要原则：

- OrderSvr 的 HA 是 partition 级，而不是简单启动两个容器。
- 逻辑路由 key 必须和 OrderSvr 自己的 partition key 完全一致。
- 同一个 `location + market + symbol` 是一个热点 book，必须重点关注单热点吞吐。
- API `code=0` 的语义必须清晰，不能让“内存队列已接收”伪装成“订单已经 durable / 可查询”。

当前 OrderSvr 持久化使用 Chronicle Queue journal，并配合 snapshot、commit marker、replication、readiness guard 做恢复。

---

### 3.3 TradeSvr

TradeSvr 是账户、资金、持仓、风控和交易状态核心。

职责：

- 账户资产；
- cashIn / cashOut；
- Position；
- 保证金；
- 杠杆；
- 风险校验；
- 订单 Newing -> New 等风控确认；
- 成交后的资金 / 持仓变更；
- 强平相关账户计算；
- Trade partition HA。

原则：

- OrderSvr 与 TradeSvr 必须通过 location / partition 正确路由到当前 primary。
- TradeSvr client 必须预连接，不能依赖首单时临时建立物理连接。
- Web 上的账户 / 持仓 / 强平价展示不能反向污染 TradeSvr 职责。

当前强平设计方向：

- TradeSvr 负责持续计算账户 / 持仓风险；
- LiqSvr 负责强平执行策略；
- 前端可以组合展示 ADL 等级 / 强平信息，但不能把核心风险逻辑搬到前端。

---

### 3.4 ProjectionSvr

ProjectionSvr 是**交易核心状态的持久化投影层**。

必须牢记：

> **ProjectionSvr 同时消费 OrderSvr 和 TradeSvr 数据。**

它不是只接订单，也不是只接成交。

职责：

- 消费 Order journal / committed projection event；
- 消费 Trade mutation / projection event；
- 更新 MySQL durable projection；
- 维护 watermark；
- 为历史查询、审计、重启恢复验证提供落库状态。

已经建立的关键表包括：

- `dc_order_projection_watermark`
- `dc_order_projection_event`
- `dc_trade_projection_watermark`
- `dc_trade_projection_event`
- `dc_trade_projection_mutation`

修改 Projection 架构时，不能把 Order / Trade 任意一边漏掉。

---

### 3.5 MDSvr

MDSvr 负责实时行情生产与发布。

职责：

- 实时成交；
- order book / market data；
- Kline；
- 行情订阅；
- 通过 GW 对 Web / API 提供实时行情。

历史行情：

- Kline / market trade 等历史数据进入 ClickHouse；
- 历史查询由 AdminSvr 提供；
- Web 不应知道 MDSvr 实例拓扑。

当前明确方向：

> 实时订阅走 GW；历史查询走 AdminSvr + ClickHouse。

当前 Kline 不以 RocksDB 作为主历史查询方案。

---

### 3.6 RobotSvr

RobotSvr 是流动性机器人，不是普通 Demo bot。

核心目标：

- 提供 10+10 等多档盘口；
- 根据总金额在不同档位分配数量；
- stale quote 自动撤单；
- 用户挂到顶档时可以主动点掉；
- 用户与 Robot 成交后自动补单；
- 外部行情跟随 Binance；
- Kline 走势 / 成交量尽量和 Binance 一致，可按比例缩放；
- 后续支持外部对冲。

最重要的架构约束：

> **RobotSvr 只连接 GW。**

不要让 Robot 直接依赖 OrderSvr / MDSvr / TradeSvr 物理地址。

外部 Binance 数据链：

`Binance -> APSSvr -> GW -> RobotSvr / MDSvr`

---

### 3.7 APSSvr

APSSvr 是外部市场适配器。

当前 Crypto 阶段负责：

- Binance Futures WebSocket；
- bookTicker；
- aggTrade；
- depth；
- ticker；
- markPrice 等。

APSSvr 不做核心交易业务。

Mac / Colima 开发环境下，APSSvr 外部访问通过现有代理链。

**绝对不要随意修改 / 重启 Mac 的 v2rayN / xray。**

Mac 10808 必须视为只读基础设施。

---

### 3.8 LiqSvr

LiqSvr 负责 liquidation 执行。

职责方向：

- 接收需要强平的账户 / 持仓；
- 生成减仓 / 平仓指令；
- 强平 IOC；
- Insurance Fund / ADL 流程协调。

不要把 LiqSvr 和 TradeSvr 的职责混在一起：

- TradeSvr：账户风险计算、资金、持仓；
- LiqSvr：达到条件后的强平执行。

---

### 3.9 AdminSvr / ManagerSvr / LoginSvr

**LoginSvr**
- 登录、session、认证。

**AdminSvr**
- 平台 / 租户管理类聚合接口；
- 历史 Kline / market data 查询；
- OpenAPI 中适合聚合的非实时管理接口。

**ManagerSvr**
- 运行态管理；
- Robot runtime；
- 服务管理 / 监控类能力。

三者不能代替交易核心。

---

## 4. 三套 Web：产品边界与文档交付

系统不是一个 Web，而是三套相互独立、可以分别部署和演进的 Web。后续会话不能把三套 Web 混成一个工程，也不能把平台管理能力重新塞回 Trade Web。

### 4.1 Platform Web（平台管理端）

面向平台运营 / 管理员。

核心能力：

- 平台管理员登录；
- 租户申请审核；
- 审核通过后生成 / 分配唯一 `location`；
- 租户状态管理；
- Order / Trade / MD 集群分配与路由管理；
- 全平台配置；
- 服务运行状态 / 管理能力；
- 平台级审计和运营管理。

边界：

- Platform Web 管理“整个平台”；
- 不作为普通交易员的交易终端；
- 不承载核心撮合、资金、持仓业务逻辑；
- 后端主要通过 GW / AdminSvr / ManagerSvr 等管理接口访问。

必须提供独立的客户/运营文档：

`docs/web/PLATFORM_WEB_GUIDE.zh-CN.md`

文档应该站在平台运营人员角度说明：

- 如何登录；
- 如何审核租户；
- location 如何产生；
- 如何查看 / 调整集群路由；
- 如何管理租户；
- 常见操作与异常处理。

### 4.2 Tenant Web（租户 / Broker 管理端）

面向租户 / Broker 管理员。

已知独立仓库：

`bliplink/dc-saas-tenant-web`

核心能力：

- 租户申请入口；
- 租户登录；
- Broker / Tenant 基本资料；
- 客户账户管理；
- 创建交易账户；
- API Key 管理；
- 客户资金操作；
- 租户级配置；
- 进入 / 导航到核心 Trade Web；
- 后续可以扩展 Broker 自有品牌 / 配置能力。

边界：

- Tenant Web 管“这个 Broker 自己的业务”；
- 不显示其它 location 的数据；
- 不直接访问 OrderSvr / TradeSvr 物理实例；
- 与核心交易服务仍通过 GW / 管理 API 交互。

必须提供独立客户文档：

`docs/web/TENANT_WEB_GUIDE.zh-CN.md`

内容至少包括：

- 租户申请；
- 审批后的登录；
- 客户 / 交易账户创建；
- API Key 创建和权限；
- 充值 / 提现；
- Broker API 接入入口；
- 如何进入 Trade Web；
- location 与客户账户的关系。

### 4.3 Trade Web（专业交易终端）

已知独立仓库：

`bliplink/dc-trade-web@saas-crypto`

发布镜像：

`ghcr.io/bliplink/dc-saas-trade-web:saas-crypto`

Trade Web 面向普通 Trader / Broker 客户，是核心交易页面。

核心能力：

- 实时行情；
- TradingView / Kline；
- Order Book；
- 下单；
- Limit / Market；
- IOC / FOK；
- PostOnly；
- ReduceOnly；
- Conditional / Trigger；
- TP / SL；
- Cancel / Cancel All；
- Open Orders；
- Order History；
- Trade History；
- Positions；
- Account Info；
- 资金 / 保证金 / 未实现盈亏；
- Desktop；
- Mobile。

边界：

- Trade Web 只关注交易；
- 不重新放置平台租户审核、系统集群管理等平台功能；
- 实时交易与实时行情统一通过 GW；
- 历史行情查询通过 AdminSvr + ClickHouse 的统一接口；
- 前端不应该知道 OrderSvr / TradeSvr / MDSvr 的物理节点。

必须提供独立用户产品文档：

`docs/web/TRADE_WEB_GUIDE.zh-CN.md`

该文档必须站在最终交易用户角度写，不描述后端微服务架构，重点说明“用户能做什么、如何操作、订单类型和风险含义”。

### 4.4 三套 Web 的导航关系

推荐产品关系：

```text
Platform Web
  └─ 管全平台 / 租户 / 路由

Tenant Web
  ├─ 租户申请
  ├─ 租户登录
  ├─ 客户 / API Key / 资金管理
  └─ 导航到 Trade Web

Trade Web
  └─ 专注专业交易
```

Trade Web 一级导航可以提供“租户”入口，但应直接导航到 Tenant Web 主页面，不在 Trade Web 内复制租户管理二级菜单。

### 4.5 Web UI 基线

UI 目标：

> 对标 Bybit 等成熟衍生品交易界面，但不复制其后端架构。

三套 Web 需要保持统一品牌风格：

- 蓝色主色；
- 黑灰交易背景；
- 登录页 / 顶部导航 / 菜单布局保持品牌一致；
- Platform / Tenant 偏管理；
- Trade Web 偏专业交易。

---

## 5. 对外 OpenAPI：Broker、Trader、Tenant

API 是本产品的正式对外能力，不只是内部调试接口。客户既可以直接使用本平台 Web，也可以完全基于 API 构建自己的 Broker / Trader 系统。

当前规范文件：

`docs/openapi/crypto-openapi-v1.yaml`

当前 OpenAPI 明确复用 GW 原生 HTTP transport，不额外引入 OpenApiSvr；业务语义仍由 LoginSvr、OrderSvr、TradeSvr、MDSvr、ProjectionSvr、AdminSvr、ManagerSvr 等服务负责。

### 5.1 Broker API：客户可以把本平台作为交易核心

Broker API 面向“自建 Broker / 经纪商后台”。

典型场景：

> 客户自己开发网站、App、CRM、账户系统或 Broker 后端，然后通过 Broker API 把订单和账户操作接入本平台交易核心。

Broker API 必须支持：

#### 客户生命周期

- 创建客户；
- 创建客户交易账户；
- 查询客户；
- 查询客户状态；
- 客户与 `location` 隔离；
- 客户 API Key / 权限管理。

#### 资金

- 客户充值 / cashIn；
- 客户提现 / cashOut；
- 查询客户余额；
- 查询资金流水；
- 必须限制在当前 Broker / location 范围内。

#### 代客交易

Broker 可以指定自己管理的 customer / trading user：

- 代客户下单；
- 代客户撤单；
- Cancel All；
- Limit；
- Market；
- IOC；
- FOK；
- PostOnly；
- ReduceOnly；
- Conditional / Trigger；
- TP / SL。

交易指令本身尽量与 Trader API 共用统一 order schema，不另造两套订单协议。

#### 客户查询

Broker 可以查询自己名下客户的：

- Open Orders；
- Order History；
- Trade History；
- Position；
- Balance；
- Margin / risk；
- Account / trading configuration。

Broker **不能**越过自己的 location 查询其它 Broker 数据。

必须提供面向客户的 Broker 接入文档：

`docs/api/BROKER_API_GUIDE.zh-CN.md`

文档必须至少包含：

- 适用场景；
- API Key 创建；
- 签名方式；
- 登录 / session；
- 权限模型；
- customer / user 参数含义；
- location 隔离；
- 创建客户完整示例；
- 充值示例；
- 代客户下单示例；
- 撤单示例；
- 查询订单 / 成交 / 持仓 / 资金示例；
- 错误码；
- rate limit；
- 幂等 / ClOrdID；
- WebSocket 行情 / 交易事件订阅。

### 5.2 Trader API：普通用户也可以直接使用 API

普通 Trader 不需要成为 Broker，也可以使用 API Key 交易自己的账户。

Trader API 面向：

- 量化用户；
- API Trader；
- 自建交易界面的普通客户；
- 自动化策略。

Trader 可以：

- 创建 / 管理自己的 API Key；
- 查询自己的账户；
- 查询自己的余额；
- 查询自己的持仓；
- 下单；
- 撤单；
- Cancel All；
- 查询 Open Orders；
- 查询历史订单；
- 查询成交；
- 订阅实时行情；
- 订阅自己的订单 / 成交 / 账户事件。

权限原则：

- Trader 只能操作自己的 UserID / account；
- Trader 不能创建其它客户；
- Trader 不能替别人充值 / 提现；
- Trader 不能用请求 content 自己扩大 session 权限；
- API Key permission snapshot 在登录后对 session 生效。

必须提供独立普通用户 API 文档：

`docs/api/TRADER_API_GUIDE.zh-CN.md`

文档应该尽量接近成熟交易所开发者文档体验，提供可直接复制运行的请求示例。

### 5.3 Tenant API：租户自建整套业务系统

Tenant API 比单一 Trader API 范围更大，适合租户基于交易核心开发自己的 SaaS / Broker 平台。

Tenant 可以：

- 创建交易账号；
- 管理 user；
- 管理 API Key；
- 资金操作；
- 下单 / 撤单；
- 查询；
- 对接自己的行情；
- 对接自己的 Robot；
- 在权限允许范围内使用平台提供的行情、品种和流动性能力。

Tenant API 仍必须受 location 隔离。

必须提供：

`docs/api/TENANT_API_GUIDE.zh-CN.md`

### 5.4 Broker API 与 Trader API 的关系

核心原则：

> **Broker 和 Trader 共用统一交易核心与统一订单协议，差别主要是“代表谁操作”和权限范围，而不是重新开发一套撮合接口。**

例如：

```text
Trader placeOrder
  user = API Key owner

Broker placeOrder
  broker = API Key owner
  customer/user = Broker 名下被代理交易账户
```

两者最终都应通过：

`Client -> GW -> OrderSvr -> TradeSvr`

### 5.5 API 鉴权与安全原则

对外 API 必须明确：

- API Key；
- Secret Key；
- HMAC-SHA256 签名；
- expiry；
- session；
- permission；
- rate limit；
- location；
- UserID；
- Broker customer scope；
- 幂等；
- ClOrdID；
- replay protection；
- API Key 禁用 / 轮换。

禁止：

- 仅靠前端隐藏字段做权限；
- 让 Broker 请求跨 location；
- 让 Trader 指定别人的 UserID；
- 通过 request content 提升权限。

### 5.6 Open API 限流（当前已实现）

GW 已实现独立的 OpenAPI Token Bucket 限流：

`OpenApiRateLimitSecurityCheck`

当前已经接入 GW `securityChecks`。

当前 profile：

| Profile | client_type | QPS | Burst | Scope |
|---|---|---:|---:|---|
| TRADER_STANDARD | API | 100 | 30 | sessionId |
| TENANT_STANDARD | TenantAPI | 20 | 10 | sessionId |

当前行为：

- `WEB` session 不进入该 OpenAPI limiter；
- signed `POST /api` 主要用于 API Key 登录交换，不消耗后续业务 session bucket；
- `POST /httpapi/` 的 API/TenantAPI session 业务请求受限；
- 每个受限请求当前统一消耗 1 token；
- 超限：`10003 RATE_LIMIT_EXCEEDED`；
- 非法 profile：`10005 RATE_LIMIT_PROFILE_INVALID`。

当前尚未实现：

- per-method weight；
- 独立 `BROKER_STANDARD`；
- Binance/Bybit 风格的 endpoint weight table。

这些能力属于性能压测完成后的规划项，不能在对外文档里当作当前生产能力。

统一参考：

`docs/api/RATE_LIMITS.zh-CN.md`

### 5.7 HTTP 与 WebSocket

API 文档不能只有下单 HTTP。

需要同时提供：

**HTTP / request-response**

- 登录 / API Key login；
- account query；
- order command；
- cancel；
- cash；
- history；
- admin-style customer management（仅 Broker / Tenant）。

**WebSocket / realtime**

- bookTicker；
- depth；
- trade；
- Kline；
- order update；
- execution；
- position；
- balance / account events。

实时核心交易 / 行情优先走 GW WebSocket，历史查询可以由 AdminSvr 聚合提供。

### 5.8 API 文档最终交付形式

最终客户不应该只看到 YAML。

交付物必须包括：

1. `docs/openapi/crypto-openapi-v1.yaml` — 机器可读标准定义；
2. `docs/api/BROKER_API_GUIDE.zh-CN.md` — Broker 客户接入说明；
3. `docs/api/TRADER_API_GUIDE.zh-CN.md` — 普通 API Trader 使用说明；
4. `docs/api/TENANT_API_GUIDE.zh-CN.md` — 租户系统集成说明；
5. 从 OpenAPI / Markdown 生成的静态开发者文档站；
6. Web 中提供 Developer / API Docs 入口。

后续扩展 FX / 商品 / 债券时，优先扩展 schema 和 market/security 维度，不复制一套新的 Crypto-only API。

---

## 6. 多租户与 location

`location` 是系统最重要的租户隔离键之一。

原则：

- 租户申请时用户不需要自己填写 location；
- 平台审批时生成唯一 location；
- location 可用于分配 Order / Trade / MD 集群；
- 默认走系统路由，平台后续可调整；
- 所有订单、资金、持仓、Robot、Projection、历史数据查询必须保持 location 隔离。

生产 location 规则必须规范化。

E2E 测试 location 同样要遵守正式规则，避免因为大小写 / 长度不同造成 GW 和服务端 partition hash 不一致。

---

## 7. 核心数据流

### 7.1 下单主链

```text
Trader/Web/API
  -> GW
  -> OrderSvr current primary
  -> Order journal / replica durability
  -> TradeSvr current primary
  -> risk/account/position
  -> OrderSvr state transition
  -> matching / trade
  -> ProjectionSvr
  -> MySQL
  -> MDSvr
  -> GW
  -> Web/API subscriber
```

任何优化不能破坏：

- ClOrdID 幂等；
- OrderID 唯一；
- journal durability；
- primary / replica fencing；
- Projection 一致性；
- Order / Trade watermark；
- location 隔离。

---

### 7.2 行情链

```text
Binance
  -> APSSvr
  -> GW
  -> MDSvr / RobotSvr
  -> ClickHouse (historical)
  -> GW realtime fanout
  -> Web / API
```

---

### 7.3 Robot 链

```text
Binance reference
  -> APSSvr
  -> GW
  -> RobotSvr
  -> GW
  -> OrderSvr
  -> TradeSvr
  -> fills
  -> Robot replenish / optional hedge
```

Robot 不直连核心物理节点。

---

## 8. HA / 分区原则

核心分区当前按 ZooKeeper assignment 管理。

必须区分：

- logical service：`OrderSvr` / `TradeSvr`
- physical node：`OrderSvrA` / `OrderSvrB`、`TradeSvrA` / `TradeSvrB`

GW 必须按 logical key 路由到当前 partition primary。

### OrderSvr

Order partition 目前包括：

- ZK assignment；
- primary / replica；
- epoch；
- READY；
- journal；
- snapshot；
- replication；
- promotion barrier；
- commit watermark；
- recovery。

节点重启后：

> 不能只看到 container running 就开始流量。

必须等：

- replication port online；
- partition recovery；
- READY；
- snapshot / journal / assignment 一致；
- verifier PASS。

### TradeSvr

Trade partition 同样必须验证：

- A/B role；
- partition READY；
- role reversal；
- watermark continuity；
- restart recovery；
- GW reconnect。

---

## 9. 数据存储职责

### MySQL

主要存：

- tenant；
- user；
- balance projection；
- order projection；
- trade projection；
- robot configuration；
- 管理数据。

MySQL 不是高频行情主存储。

### ClickHouse

主要存：

- Kline；
- market trade；
- 大规模行情历史；
- 秒级历史查询。

目标数据规模可以达到上亿级 ticker / trade。

### ZooKeeper

用于：

- cluster assignment；
- primary / replica；
- epoch；
- readiness / routing metadata。

### Chronicle Queue

当前主要用于 OrderSvr durable journal。

重点：

- Chronicle 是嵌入式 journal，不是独立微服务；
- journal 必须配合 snapshot / compaction / recovery；
- 不能让 journal 无限增长导致节点恢复时间不可接受。

---

## 10. 当前版本约束

非常重要，后续会话不要凭版本号猜依赖关系。

当前原则：

- **gateway-api 固定为 3.0.6**
- **com.app.common 与 gateway-api 是两套独立版本**
- OrderSvr 当前新构建链已经验证 `com.app.common=3.0.14`
- `3.0.14` 主要包含 Snowflake 时钟回拨保护
- 老镜像 / 其它服务可能仍带 `3.0.13`，修改前必须查看实际 image label / jar
- **绝对不要把 gateway-api 升成 3.0.14**

任何服务版本调整，先查 dependency tree，再编译测试。

---

## 11. 部署环境基线

开发 / E2E 主环境：

- Mac mini M4 / arm64 / 24GB；
- Colima arm64；
- Docker；
- 项目：`~/dc-quant-deploy`；
- 主分支：`saas-crypto`。

代理：

- Mac 本地代理端口：`10808`
- **禁止随意 kill / restart / edit v2rayN / xray**
- Mac 10808 视为只读；
- Colima 可以通过现有转发使用 10808。

Docker：

- Mac 侧 Docker socket 偶尔不可用时，可以 SSH 进入 Colima VM 使用 `docker`；
- 不要因为 CLI socket 问题就重启整个 Colima。

---

## 12. 部署与验收目标

最终必须沉淀成“一键完整流程”：

```text
卸载
  -> 全新安装
  -> 初始化数据库 / ClickHouse / ZK
  -> 初始化平台管理员
  -> 初始化 E2E 租户
  -> 初始化租户用户 / trader / broker
  -> 初始化默认 Robot
  -> 等待核心 partition READY
  -> validate-saas
  -> tenant lifecycle E2E
  -> broker API E2E
  -> projection consistency
  -> robot liquidity E2E
  -> trading-rule E2E
  -> non-destructive load test
  -> restart / role reversal / recovery test
  -> final report
```

### 默认 E2E 数据

应保留一组标准 E2E fixture，用于安装后自动验证。

当前长期 fixture 方向：

- location：`E2E001`
- robot：`default-depth10`

用户名 / 密码必须由部署环境变量初始化和输出，不要把真实生产密码硬编码到 Git。

安装脚本最后应该明确打印：

- Platform URL；
- Platform admin username；
- Platform admin password / password source；
- Tenant URL；
- E2E tenant location；
- Tenant username；
- Tenant password / password source；
- Trade URL；
- Robot runtime status。

---

## 13. 已经验证通过的关键能力

截至 2026-09-28，以下能力已经有真实 E2E / consistency 证据：

- `validate-saas.sh --env-file .env.prod` 基础部署检查；
- 21 个预期容器；
- GW Trade route；
- Tenant lifecycle；
- Broker API；
- Projection Order + Trade 双链；
- Projection watermark consistency；
- TradeSvr role reversal；
- Trade preconnection；
- MD -> ClickHouse；
- Robot Binance WS feed；
- Robot 10+10 liquidity；
- Robot IOC hit；
- Robot replenish；
- Robot Kline / reference price；
- Open Orders / FOK / IOC / Conditional / CancelAll 等交易规则；
- OrderSvr `common 3.0.14` 兼容测试；
- OrderSvr 新有界队列 / WAL-first 测试。

---

## 14. 当前性能基线与未解决问题

这一节是后续会话最容易偏离的地方。

### 14.1 不要误判“1000 单把系统打崩”

最近 1000 / concurrency=16 的单热点盘口压力没有让核心容器直接 crash：

- 0 restart；
- 0 OOM。

但是性能结果仍然不合格。

早期问题包括：

- Snowflake `Clock moved backwards`；
- 无界 NewOrder queue；
- queue backlog 1200+；
- MassCancel 60s timeout；
- API code=0 与 durable 状态不一致。

### 14.2 已经修掉的安全问题

OrderSvr `6a6ab72` 方向包含：

- `com.app.common=3.0.14` Snowflake rollback protection；
- bounded hot-book queue；
- `ORDER_BOOK_OVERLOADED` 明确背压；
- WAL-first admission；
- accepted request 必须最终 durable；
- pending new reconciliation。

最新 admission 1000/16 验证：

- 884 accepted；
- 116 明确 `ORDER_BOOK_OVERLOADED`；
- 884 / 884 最终 durable；
- 没有“ACK 成功但 durable 丢单”。

### 14.3 仍然未解决的性能瓶颈

单热点：

`A02AA7 + BTCUSDT`

当前真实 durable 吞吐约：

> **~16 orders/sec**

这远不是最终目标。

已确认架构热点：

1. 一个 `location + market + symbol` 对应一个单线程 NewOrderWorker；
2. 每批最多 64；
3. Order state 使用 STATE + COMMIT 两阶段 journal；
4. 主节点和副本都需要 journal append；
5. initial WAL 已经 batch；
6. TradeSvr 回包后的 `Newing -> New` 仍存在逐单 durable 路径，需要继续优化；
7. callback `AsyncSeqThreadGroup` 按 userId hash，同一用户回调会落固定 lane；
8. 当前 CPU 配额较低：
   - Order A/B 约 1.5 CPU / node；
   - Trade A/B 约 0.5 CPU / node；
   - GW 约 0.35 CPU。

Chronicle Queue 单独微基准达到数万到数十万 writeText/sec，因此 **Chronicle 库本身不是 16 orders/sec 的根因**。

### 14.4 OrderSvr 节点恢复问题

当前还发现一个重要问题：

OrderSvr 节点重建 / restart 时，部分 partition 可能长期：

`PARTITION_NOT_READY`

并出现：

`EPOCH_NOT_ADVANCED`

即：

- ZK candidate epoch 和本地 recovered source epoch 相同；
- same-epoch restart 安全恢复逻辑需要继续验证；
- lifecycle 当前使用**单线程**遍历和同步恢复 partition；
- 不应通过反复 restart 掩盖。

当前 journal / snapshot 体量也需要治理：

- OrderSvrB journal 约 1.4GB；
- snapshot 总量约 13MB；
- P089 journal 约 138MB；
- snapshot 约 6.4MB。

后续必须继续验证：

- same-epoch restart；
- snapshot boundary；
- journal compaction / rebase；
- restart RTO；
- 是否需要并行 partition recovery。

---

## 15. 压测方法原则

压测不能只看 HTTP success。

必须同时看：

- HTTP accepted；
- `ORDER_BOOK_OVERLOADED`；
- durable `dc_orders` count；
- Rejected；
- Newing -> New 收敛；
- execorders；
- posting；
- position；
- Projection watermark；
- queue depth；
- CPU；
- memory；
- OOM；
- restart count；
- replication timeout；
- p50 / p95 / p99；
- overload 后恢复时间。

尤其：

> `code=0` 的语义必须和最终 durable 结果一起验证。

单热点压测和多 symbol / 多 location 压测要分开。

---

## 16. Web / Trading 产品方向

Trade Web 对标专业衍生品交易体验。

关键要求：

- 下单区域首屏可见；
- TradingView 深色背景；
- Positions / Account Info 对齐；
- Open Orders 稳定；
- Kline 初始失败不能让整个交易终端失效；
- 15s timeout 后按钮恢复；
- ReduceOnly / Market Close / TP/SL 使用标准 CLOSE；
- FOK；
- IOC；
- Conditional Limit；
- TriggerLimit；
- 精度边界；
- CancelAll 部分失败；
- 500 Open Orders 内部限制，DOM 渲染限制；
- Desktop / Mobile 都要真实页面验收。

不要为了后端排障随意改动 Web 已经稳定的交互。

---

## 17. 开发与操作纪律

后续会话必须遵守：

1. **先读本文件，再开始任务。**
2. 先确认当前目标，不要从 Projection 跳回 Order、从 Robot 跳到无关服务。
3. 验证过程中不要没事重建服务。
4. 只重启需要重启的单个服务。
5. HA 服务必须按 A -> READY -> B -> READY 滚动。
6. 每次修改前先 `git status` / diff。
7. 不要把已有未提交改动一起误 commit。
8. 不要覆盖其它并行 worktree 的代码。
9. Git push 可通过本机 10808，但**不能修改代理本身**。
10. 用户要求短步骤推进，长任务按 30~60 秒粒度持续报告进度。
11. 任何“PASS”必须有真实 E2E / consistency / runtime 证据。
12. 不能把 mock / 效果图当真实页面验收。
13. 不能把容器 running 当 cluster READY。
14. 不要为了解决测试脚本问题去改生产业务逻辑，先区分测试缺陷还是系统缺陷。

---

## 18. 后续优先级

当前正确推进顺序：

### P0 — OrderSvr 性能与恢复

- 修复 / 验证 same-epoch restart；
- 保证重建节点可以重新 READY；
- 降低 hot-book 单线程链路延迟；
- 批量化 Trade callback durability；
- 保持 WAL-first / bounded queue；
- 压测至少做到过载可控、无假成功、无丢单；
- 完成单热点 / 多热点两类 benchmark。

### P1 — 完整卸载 / 安装 / 初始化 / 自动 E2E

同时完成正式客户文档交付：

- Platform Web 使用文档；
- Tenant Web 使用文档；
- Trade Web 用户文档；
- Broker API 文档；
- Trader API 文档；
- Tenant API 文档；
- OpenAPI YAML -> 静态开发者文档站；
- Platform / Tenant / Trade Web 中正确的文档与导航入口。

沉淀一整套脚本：

- uninstall；
- install；
- config generation；
- platform admin seed；
- E2E tenant seed；
- trader / broker seed；
- default robot seed；
- credentials summary；
- full acceptance。

### P2 — 最终 HA / fault acceptance

- Order A/B restart；
- Trade A/B role reversal；
- MD HA；
- Liq HA；
- GW reconnect；
- snapshot/journal recovery；
- Projection continuity。

### P3 — Web E2E runner

Playwright runner 之前有依赖 / 网络问题。

这属于测试基础设施问题，不等于交易系统失败。

---

## 19. 新会话开始时应该先做什么

新的会话继续本项目时，先执行：

```bash
cd ~/dc-quant-deploy
git branch --show-current
git status --short
git log -5 --oneline
```

然后阅读：

```text
docs/DC_CORE_ARCHITECTURE_BASELINE.zh-CN.md
```

再读取当前正在处理服务的代码 / commit / runtime 状态。

如果当前任务是部署 / 验收，再检查：

```bash
./validate-saas.sh --env-file .env.prod
```

如果当前任务是 Order HA / 性能，则先检查：

- Order A/B ImageID / revision；
- common version；
- ZK partition assignment；
- READY；
- 19121 / 19122；
- verifier；
- 当前是否有遗留 stress 进程；
- 当前 E2E tenant 是否有活动订单。

---

## 20. 一句话架构原则

> **这是一个以 location 隔离的多租户交易核心：GW 统一入口，Order 管订单与撮合入口，Trade 管账户资金持仓与风控，Projection 同时落 Order/Trade，MD 负责实时行情，ClickHouse 负责大规模历史行情，Robot 只通过 GW 提供流动性，核心服务按 partition 做 HA；任何优化都不能破坏 durable、幂等、隔离、路由和恢复语义。**
