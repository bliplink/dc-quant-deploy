# OpenTradingCore 项目总览与跨账号交接

> 更新时间：2026-10-01
> 目标读者：新的 ChatGPT/Codex 会话、另一 GitHub/ChatGPT 账号、接手研发/部署人员。
> 开始任何修改前，请先完整阅读本文，并重新 fetch 对应仓库最新分支。文中的 commit 仅是快照，不是永久锁定版本。
>
> 当前问题清单：[`docs/CURRENT_ISSUES_20261001.zh-CN.md`](docs/CURRENT_ISSUES_20261001.zh-CN.md)

---

## 0. 2026-10-01 最新接续点（优先于下文旧快照）

- 2026-10-01 新增真实 Demo 业务链路验收：通过公开 `ManagerSvr.tenantApplication` 申请单品种租户 `T17QGO`，自动审批及 `dc_tenant_liquidity_bootstrap=COMPLETE`，Robot 为 `NOTIONAL_ZONES/RUNNING`；**这是旧模板的 10 买 + 10 卖、20 单基线**，每侧金额按 3/3/4 区域分布，约 463 USDT。新注册交易员经 `Demo=1` 入金 1000，IOC 买入 0.0001 BTC 成交，订单/成交/Long 持仓一致；随后 Reduce-Only IOC 卖出平仓，最终持仓、占用保证金和交易员活动单均为 0。可复跑脚本：`tests/run-auto-tenant-trading-e2e.py`（现已调整为新 40 单模板；先 export 当前本机受保护 env；所有业务写入走 API，MySQL 只读验收）。此为单次业务验收，**不是**长期稳定性或外部 GA 证明。
- **2026-10-01 流动性目标修正为总共 40 档：买 20 + 卖 20。** Robot 引擎原本支持 20/20，问题在 Admin 自动审批试用租户的默认模板仍写死 10/10 和金额区 3/3/4。`TrialLiquidityBootstrapWorker` 现改成 20/20、金额区 6/6/8、权重仍 3/3/4；Admin 63 项测试通过，提交 `0409add` 已快进推送到 `saas-crypto`，本机镜像 `local/dc-saas-adminsvr:trial-depth40-20261001`。新试用租户 `Z669FQ` 自动初始化 `COMPLETE`，Robot `RUNNING/40`；公开 `MDSvr.queryPublicMarket` 按原有设计只返回每侧前 10 档，并不表示后 10 档没有挂单。**既有** `T17QGO` 和 `E2E001` 仍是旧 10/10 配置，未静默迁移。
- 租户管理热更新真实通过：新租户 `RTTKFL` 使用 `TenantAdmin` 会话调用 `tenantLiquidityProfileAdmin` 的 `UPSERT → APPLY`，先从 20/20 改为 15/15（Robot 30 单），再恢复 20/20（40 单），Robot 容器 ID 未改变。验收脚本：`tests/run-tenant-liquidity-hotedit-e2e.py`。首次试验 `PYFT1S` 因脚本误用普通 `WEB` 会话被控制面安全策略拒绝；没有修改该租户 Robot 参数，改为真实 `TenantAdmin` 身份后通过。
- Robot 稳定性：旧 10/10 配置下连续 50 轮吃卖盘前三档并 Reduce-Only 平仓通过，但曾在第 5 轮出现 5 秒未补齐、`QUOTE_RECONCILIATION_RETRY`/60 秒退避。合并远端报价桥接修复与本地 Broker/Trader API 隔离后，新 20/20 配置仍复现“最终核对前客户 IOC 吃掉 3 档 → 20/17 被误判严重失败”。现仅对**剩余挂单是目标集子集、无额外/重复报价**的情况走短周期补单，并以 10 秒为界；真正的异常仍保留安全退避。Robot 107 项单测通过；提交 `264c7e1` 已快进推送到 `saas-crypto`（包含 Broker/Trader API 隔离），本机镜像 `local/dc-saas-robotsvr:depth40-replenish-20261001`（Image ID `sha256:50e1087aeefe539e37a82e490149cc8555f03a31951c3f8f81a20162988d6479`）。
- 40 档复测：`RTTKFL` 连续 20 轮、`PYFT1S` 连续 50 轮真实 IOC 吃卖盘前三档，均每轮回到 `RUNNING/40`，公开前十档买卖数量采样始终 10/10；每轮通过 Reduce-Only 平仓，最终测试账户 0 持仓、0 活动单。50 轮中有 3 轮前十档**金额**短暂偏离（档位数量未减少，最长约 2.05 秒），一次 placeOrder/平仓请求约 2.14 秒；请求 p95 约 7.7 ms、无 timeout。这些尾部抖动及全量 20+20 行情快照仍待继续量化，不能宣称 Robot 长稳或 placeOrder timeout 问题彻底解决。脚本：`tests/run-robot-replenishment-e2e.py`。本轮三个新测试租户 `Z669FQ`、`PYFT1S`、`RTTKFL` 已在确认无非零持仓/活动客户单后经平台 API 暂停，Robot `STOPPED/0`；没有直接删库。`validate-saas.sh` PASS，21 个预期容器运行。
- 本轮发现并修复自动分配 location 的跨服务规则不一致：Manager 旧随机生成器可能分配数字开头 6 位码，Admin 用户注册只接受字母开头，导致新租户 Robot 初始化在 `CREATE_MAKER` 无限重试。Manager 新生成器首位固定字母；Manager/Admin 管理与查询路径兼容已经分配的数字开头 6 位码。本地 Manager/Admin 镜像分别为 `local/dc-saas-managersvr:tenant-location-fix-20261001` 和 `local/dc-saas-adminsvr:tenant-location-fix-20261001`，重启后均 0 restart；此前卡住的 `4MWPTX` 自动续接至 COMPLETE。试运行产生的 `YDE33P`、`4MWPTX` 已通过平台 API 正常暂停，Robot `STOPPED/0`，未删库。
- 本机匿名交易页面当前可见 `E2E001` 与本轮新租户 `T17QGO` 的双侧盘口；`T17QGO` 页面实际显示买卖各 10 档及不同档位数量。带分区 key 的 `MDSvr.queryPublicMarket` 返回 20 档；旧公网匿名空盘口仍需独立浏览器复测，不能据本机结果宣称公网已修复。直接调用该 HTTP API 时必须附 `key=location\u001f4\u001fBTCUSDT`，缺失 key 会得到网关 `9000`，不是 MDSvr 崩溃。
- API 开发者文档已从 `dc-quant-deploy/docs/openapi/crypto-openapi-v1.yaml` 和公开指南构建成独立静态 Docker 站点：`https://api.opentradingcore.com/`。文档功能提交 `127c8b9`；当前正式容器 `opentradingcore-api-docs` 使用 **Actions 构建的 GHCR 镜像** `ghcr.io/bliplink/opentradingcore-api-docs@sha256:9b86559d5e636cae906b3280a51902ad231893d518a6beb44ccb1f5525cf86ee`，其源码 revision 为 `16e453c`，host network 监听 `18096`。Cloudflare Tunnel 映射该域名到 `127.0.0.1:18096`。主站没有 `/docs/` 代理，也没有独立的 Docs 菜单项；桌面和手机菜单中的 **API** 均直接打开该二级域名。主站提交 `fe5653a`，运行镜像 `local/opentradingcore-web:sha-fe5653ad60e5`。
- 公开文档现有 `/en/` 与 `/zh/` 两套首页、接入指南、Trader/Broker、实时订阅、限流、状态页及由同一 YAML 生成的 28 方法目录。语言切换优先停留在相同主题页；另一语言尚无页面时回到其总览。**英文完整字段级参考尚未翻译完**，现有英文页明确链接中文全文，不能宣称全量字段双语。`scripts/update-public-api-docs.sh` 负责成对校验、接受翻译版本、构建和本机部署；hash manifest 防单边更新，发布源变更要求同步修改中英文 changelog。构建/部署说明见 `docs/public-api/README.md`。
- 新增 `publish-public-api-docs.yml`：push 时 Actions 校验并构建 amd64/arm64 镜像，推 GHCR SHA tag；**仅手动 dispatch** 才运行部署作业，按不可变 digest 拉取到本机，健康检查失败回滚。2026-10-01 `16e453c` 的 [Actions 发布运行](https://github.com/bliplink/dc-quant-deploy/actions/runs/36818355380) 和 [开发文档校验](https://github.com/bliplink/dc-quant-deploy/actions/runs/36818355366) 都已成功，说明 Billing 限制当前没有阻挡本流程。部署是从 GHCR digest **本机手动**执行，不是 self-hosted runner 作业。仓库仍 **0 个 self-hosted runner**，`saas-crypto` **无分支保护**，`local-api-docs` **无环境审批**；启用 Actions 主机部署前必须注册仅限本仓库、带 `otc-api-docs` 标签的 Mac ARM64 runner，并配置分支保护与环境审批。旧自动部署版本的 publish 虽成功，但排队部署已取消，避免未来误切旧镜像。
- API YAML validator、28/28 方法/请求 schema 检查和英文/中文 MkDocs strict build 通过；公网 `/en/`、`/zh/`、两版快速开始、YAML、方法目录均能返回 200。候选站点浏览器验证同主题语言切换、英文缺页回退、中文移动端无横向溢出且无 pageerror；正式 GHCR 文档容器 healthy、0 restart、无 OOM。旧正式文档容器 `opentradingcore-api-docs-previous-20261001131216` 保留作回滚。**公网稳定性未完全过门禁**：GHCR 切换后的首次多 URL curl 中，英文目录曾一次 reset、英文 YAML 曾一次超时；同一时段本机 origin 对对应路径连续 3/3 返回 200，随后公网 direct retry 6/6 返回 200，失败请求未见于 nginx access log。尚不能断言是 Cloudflare edge、Tunnel 或本机外网链路，需独立持续探测并关联 cloudflared 连接日志，不能据这次短测宣称外部链路稳定。
- 公开站点当前为 **Developer Preview / demo funds only / NOT External GA**。本轮用户视角检查发现：未登录 Trade Web 的 E2E001 Order Book 为空，而登录后有买卖各 10 档；Robot/Tenant Liquidity 同时显示运行中、20 单。此为待查现象，不能直接归因为 MDSvr 或 Robot。主站公开目录含可点击的 `SUSPENDED` 租户；租户控制台 Liquidity 表格操作列在桌面和手机上均不易发现，Settings 样式也不统一。公开前还需邮箱激活门禁、长时间交易稳定性/异常切换、Broker/Trader API 真正外部接入验收。详见后续任务，不要把单次容器健康当成稳定性结论。
- 下文“Trade Web 黑屏待修”和 `docs/CURRENT_ISSUES_20261001.zh-CN.md` 中相同内容是旧快照：之后的完整 Web E2E、300/16、Order 256/256 READY、Trade P000 双向切换均已通过。继续工作时先以实时容器、远端 Git 和最新测试证据复核，勿重复执行已通过的大型压测。

---

## 1. 系统目标与目的

**OpenTradingCore** 是一套可复用的、多租户交易基础设施。

当前先落地 Crypto / 加密货币，但长期目标是复用同一交易核心继续扩展到 FX、商品、债券和其他标准化交易品种。

产品不是单一交易所网页，而是：

`交易核心 + 多租户 + Web + API + 集群/高可用`

核心产品口号：

> **免费构建属于自己的交易系统**

最终目的：让用户不必从零开发订单、账户、持仓、行情、风控和高可用基础设施，即可拥有自己的独立交易环境。

两种主要使用方式：

1. **开箱即用**：申请租户 -> 平台审批 -> 分配 location/集群 -> 直接使用平台专业交易 Web、行情、账户、持仓和风控。
2. **深度定制**：通过 Broker / Trader / Tenant API + AI 开发自己的前端、后台、资金托管接入、数据源、Robot、策略和外部市场连接。

平台负责交易核心；**实际资金托管由租户负责**。平台提供账户与充值/提现记账 API，但不要求真实资产托管给 OpenTradingCore。

一句话目标：

> **OpenTradingCore 要做的是一套可直接使用、可通过 API 深度定制、支持多租户隔离和集群高可用、可扩展到多资产类别的专业交易核心，而不是单纯做一个加密货币交易网页。**

---

## 2. 不可偏离的架构原则

### 多租户

- 每个租户的用户、账户、持仓、订单、配置、API Key、权限和路由必须隔离。
- Broker 与 Broker 必须隔离。
- 租户可使用平台行情/品种/Robot，也可自行接行情、Robot、策略和外部市场。

### tenant_code == location

当前统一规则：**公开租户 code 与内部 location 使用同一个值。**

- 用户申请租户时不填写 code/location。
- 平台审批时生成 6 位唯一 location。
- 该值同时作为公开 code、内部 location 和 Web 交易路由标识。
- 不要重新引入两套不同 ID。

### GW 不承载业务

GW 负责 HTTP、WebSocket、服务发现/路由、认证入口、限流、连接管理和 OpenAPI 传输；核心交易业务计算必须在业务服务中。

### Browser 不直连数据库

任何 Web 都不能直接查询 MySQL / ClickHouse / RocksDB。统一走 HTTP/WebSocket -> GW -> 后端服务。

### 行情与 Kline

- 实时行情/Kline：GW 订阅。
- 历史 Kline：AdminSvr 查询。
- Kline 历史持久化：ClickHouse。
- Web 不需要知道 MDSvr 的物理位置。

---

## 3. 核心交易链路

```text
Client / Web / API
        |
        v
       GW
        |
        v
    OrderSvr
        |
        v
    TradeSvr
        |
        +-------------------+
        |                   |
        v                   v
 ProjectionSvr          Account/Position/Risk
        |
        v
 Database / Query Views
```

**ProjectionSvr 同时接收 OrderSvr 和 TradeSvr 的数据。不要把 ProjectionSvr 理解为只消费订单数据。**

市场数据大致链路：

```text
External Market / Robot / Trading Events
                 |
                 v
               MDSvr
                 |
          +------+------+
          |             |
          v             v
    realtime -> GW   history -> ClickHouse
                         |
                         v
                     AdminSvr
```

---

## 4. 源码仓库清单

当前 SaaS Crypto 主研发分支统一为 `saas-crypto`；主页 `opentradingcore-web` 使用 `main`。

| 仓库 | 服务/用途 | 2026-09-30 快照 |
|---|---|---|
| `bliplink/com.app.dc.ordersvr` | OrderSvr：订单接入、生命周期、交易路由 | `6a6ab725` |
| `bliplink/com.app.dc.tradesvr` | TradeSvr：账户、资金、持仓、交易状态 | `2330d19f` |
| `bliplink/com.app.dc.projectionsvr` | ProjectionSvr：Order + Trade 投影/数据库视图 | `2d54c9d3` |
| `bliplink/com.app.dc.mdsvr` | MDSvr：行情、盘口、成交、Kline | `d3c1f2f2` |
| `bliplink/com.app.dc.liqsvr` | LiqSvr：强平/流动性相关核心能力 | `5df0879f` |
| `bliplink/com.app.dc.robotsvr` | RobotSvr：流动性 Robot、外部市场/对冲 | `9b0ddbde` |
| `bliplink/gw` | GW：HTTP/WS 网关、路由、认证、限流 | `441b7d36` |
| `bliplink/com.app.dc.adminsvr` | AdminSvr：查询聚合、历史 Kline、公共目录 | `5c538c3b` |
| `bliplink/com.app.dc.managersvr` | ManagerSvr：租户申请/审批/location/集群分配 | `a70616b7` |
| `bliplink/com.app.dc.loginsvr` | LoginSvr：登录、Session、API Key | `9fdaf39d` |
| `bliplink/com.app.dc.apssvr` | APSSvr：外部数据/辅助服务/Binance 场景 | `c61ba05e` |
| `bliplink/com.app.common` | Java 公共基础库 | `093da440` |
| `bliplink/gateway-api` | Gateway API / 服务间协议 | `0958abdd` |
| `bliplink/dc-trade-web` | 核心交易 Web / Tenant Services / Apply | `9e298e7a` |
| `bliplink/dc-saas-tenant-web` | 租户控制台 | `e2eedbab` |
| `bliplink/dc-saas-platform-web` | 平台运营控制台 | `e4f62272` |
| `bliplink/opentradingcore-web` | OpenTradingCore 官网主页 | `4bfaee96`（main） |
| `bliplink/dc-quant-deploy` | 部署、配置、测试、OpenAPI、文档总集成 | `865a8ec2` |
| TradingView 稳定版本源 | Charting Library 受控依赖 | 独立维护 |

### 公共依赖版本

```text
com.app.common = 3.0.14
gateway-api    = 3.0.6
```

不要把两者版本混淆。

---

## 5. Web 与域名

### 主站

- Repo: `bliplink/opentradingcore-web`
- Branch: `main`
- URL: `https://opentradingcore.com`
- 作用：品牌主页、申请入口、租户目录、API/产品入口。

主页租户排序：

```text
用户数 DESC
24h 交易量 DESC
24h 成交笔数 DESC
code/location ASC
```

每页 10 条；公开列表不显示租户名称。

### 核心交易 Web

- Repo: `bliplink/dc-trade-web`
- Branch: `saas-crypto`
- URL: `https://trade.opentradingcore.com`
- 镜像历史名称：`ghcr.io/bliplink/dc-saas-trade-web:saas-crypto`

职责包括 TradingView、Order Book、下单/撤单、Open Orders、Positions、Account、成交、实时行情、Tenant Services 和租户申请页。

### 租户控制台

- Repo: `bliplink/dc-saas-tenant-web`
- URL: `https://tenant.opentradingcore.com`
- 具体租户：`https://tenant.opentradingcore.com/?location=E2E001`

通用根域名不能要求匿名用户先有 Session。

### 平台运营

- Repo: `bliplink/dc-saas-platform-web`
- URL: `https://platform.opentradingcore.com`
- 作用：平台运营、租户审核、集群/租户管理。

### 品牌统一

四站统一品牌：`OpenTradingCore`，统一 favicon。

不要重新出现：`DC | Trade`、`DC Exchange Cloud`、`DC Tenant Console`、`DC Platform Operations`。

---

## 6. Open API

Source of Truth：`dc-quant-deploy/docs/openapi/`。

主入口：`docs/openapi/README.zh-CN.md`。

机器规范：`docs/openapi/crypto-openapi-v1.yaml`。

### Trader API

只能操作自己：自己的订单、账户、持仓、成交和资金。

### Broker API

可创建客户、管理客户资料、充值/提现记账、代表客户交易、查询客户账户/持仓/历史。Broker 之间必须隔离。

### Tenant API

用于租户后台和自动化管理：用户、品种、Robot、Settings 和管理查询。

Trader / Broker / Tenant 三种身份边界不可混用。

---

## 7. RobotSvr 产品目标

RobotSvr 不是简单随机挂单，而是为租户提供可用市场流动性：

- 接收 Binance 等外部市场数据；
- 提供盘口；
- 按总金额合理分配各档挂单；
- 降低盘口延迟；
- 用户挂到盘口时可按策略主动处理；
- 与用户成交后可向外部市场对冲；
- Kline 走势/成交量尽量与参考市场一致，可按比例缩放；
- 顶档挂单超时撤单；
- Robot 只通过 GW 接入系统。

---

## 8. 集群 / HA 目标

重点包括 OrderSvr / TradeSvr / MDSvr cluster、ProjectionSvr、GW、高可用路由、分区恢复、数据恢复和节点扩容。

目标不是简单“两个容器都在跑”，而是：故障后业务可继续、RPO 受控、恢复可验证、路由能选择可用节点、冷启动和首单延迟可控。

---

## 9. 数据存储

- MySQL：租户、用户、控制面、管理配置、Projection 查询数据等。
- ClickHouse：Kline、大规模行情/成交历史，目标亿级 ticker 秒级查询。
- ZooKeeper：服务发现、集群协调、节点/角色状态。

---

## 10. dc-quant-deploy 的定位

`bliplink/dc-quant-deploy@saas-crypto` 是整套系统的集成 Source of Truth，包含：

- Docker Compose
- 环境变量
- 一键安装/卸载
- 集群配置
- MySQL / ClickHouse / ZooKeeper 初始化
- 服务配置覆盖
- 验收/压测脚本
- OpenAPI
- 产品/架构/验收文档

重要目录/文件：`compose.yaml`、`validate-saas.sh`、`docs/`、`docs/openapi/`、`tests/`。

---

## 11. 发布规则：必须统一

> **Git 是唯一源码合并点，GitHub Actions 是正式镜像唯一发布源。**

多账号/多会话并行时必须：

1. 修改前 fetch 最新远端；
2. 在最新分支上 rebase / merge；
3. 解决冲突；
4. 禁止 force push；
5. Push Git；
6. GitHub Actions 从一个确定 commit 完整 build；
7. 生成完整 Docker 镜像；
8. 部署完整镜像；
9. Playwright / E2E 验收。

### Web 镜像强制一致性

同一次 build 必须一起产生：

```text
index.html
main_<build>.js
main_<build>.css
TradingView assets
favicon
nginx config
```

**禁止把不同 build 的 index.html / JS / CSS 拼到同一个镜像。**

正式部署推荐锁 `sha-<git-commit>` 或 image digest，而不是长期只依赖移动的 `saas-crypto` tag。

---

## 12. 历史 P0：Trade Web 黑屏（后续已用完整镜像修复）

以下记录的是 2026-09-30 的历史故障，不代表 2026-10-01 的实时状态。`https://trade.opentradingcore.com/#/trade?location=E2E001` 当时出现黑屏。

已定位根因不是后端，也不是 WSS，而是静态 bundle 版本错配：

```text
index.html
  -> main_2026_09_30_01_57_13.js
  -> main_2026_09_30_01_57_13.css

但运行镜像 res/ 实际只有：
  -> main_2026_09_29_16_40_54.js
  -> main_2026_09_29_16_40_54.css
```

缺失 JS/CSS 被 nginx 回退成 HTML，浏览器报 MIME `text/html`，最终 body 为空。

**正确修复：从最新合并后的 `dc-trade-web@saas-crypto` 完整重新 build，并整体部署同一次 build 的 index/JS/CSS。不要只把 index 指回旧 bundle。**

Playwright 必须验证：HTML 200、JS/CSS 200、Content-Type 正确、body 非空、WSS 正常、console error=0。

---

## 13. GitHub Actions 当前注意事项

2026-09-30 曾出现 Actions run 标记 failure，但实际原因是 Billing/spending limit，job 根本未启动。

看到 `failure` 时先查看 job 是否真正启动，不要直接判断代码编译失败。Actions 恢复后应停止长期使用本地“衍生镜像/单文件补丁”作为正式发布方式。

---

## 14. Web 关键入口

- 主站：`https://opentradingcore.com`
- 申请：`https://trade.opentradingcore.com/#/apply`
- 交易示例：`https://trade.opentradingcore.com/#/trade?location=E2E001`
- 租户入口：`https://tenant.opentradingcore.com/`
- 具体租户：`https://tenant.opentradingcore.com/?location=<LOCATION>`
- 平台：`https://platform.opentradingcore.com/`
- API 文档：`https://api.opentradingcore.com/`（独立容器；主站不挂载 `/docs/`）

HTTPS 交易 Web 必须使用 `wss://trade.opentradingcore.com/gateway`，不能使用 `ws://...`。

---

## 15. 性能目标

- 去除 OrderSvr 人工 200ms 延迟；
- 去除 Robot 盘口延迟；
- 降低首单冷启动；
- GW/Order/Trade 预连接；
- 核心链路高并发、低延迟；
- ClickHouse 支撑亿级历史秒级查询；
- 压测同时关注服务重启、积压、GC 和恢复。

历史首单延迟定位之一：TradeSvr keyed client 未 Online 时有 100+200+400+800+1600ms 退避，最大约 3.1 秒。

---

## 16. 交易 Web 产品目标

目标是专业衍生品交易终端体验，核心能力包括：TradingView、实时行情、Order Book、Limit/Market、FOK/IOC、Conditional/Trigger、ReduceOnly、Close、TP/SL、Cancel All、Open Orders、历史订单/成交、Position、Account、Leverage、风险/强平信息、WebSocket、Desktop + Mobile。

前端不承担核心资金/持仓权威计算。

---

## 17. 访问权限

`dc-quant-deploy` 和 `opentradingcore-web` 当前为公开仓库；大部分核心后端和业务 Web 仓库为私有仓库。

另一个账号要继续开发，必须：

1. GitHub 账号有 `bliplink` 私有仓库权限；
2. ChatGPT/Codex GitHub Connector 授权到该 GitHub 账号；
3. 能读本文并不代表自动能读所有私有源码。

---

## 18. 多会话协作规则

不允许：

- `git push --force`
- `git reset --hard origin/...` 覆盖别人工作
- `git add -A` 把其他会话临时文件一起提交
- 长期只改运行容器而不回写 Git
- 混合不同 build 的 Web 静态资源
- 未检查现有容器/工作区就重建全部服务

每次必须：

```text
git fetch
git status
git log HEAD..origin/<branch>
git rebase / merge latest
test
push
GitHub Actions build
deploy immutable image
Playwright/E2E
```

如果工作期间远端出现新提交：**先合并最新远端，再发布，不发布旧产物。**

---

## 19. Mac mini 本地环境

常用路径：

```text
/Users/kong/dc-quant-deploy
/Users/kong/.dc-web-fix/dc-trade-web
/Users/kong/.dc-web-fix/dc-saas-tenant-web
/Users/kong/.dc-web-fix/dc-saas-platform-web
/Users/kong/opentradingcore-web
```

代理：`127.0.0.1:10808`；Docker：Colima / arm64。

本地工作区可能同时被多个会话使用，接手前必须先 `git status` / `git branch -vv` / `git log --oneline --decorate -20`，不要假设干净。

---

## 20. 推荐先读的已有文档

```text
docs/SAAS_PRODUCT_DELIVERY_PLAN_20260929.zh-CN.md
docs/PROJECTION_ORDER_TRADE_ARCHITECTURE_20260927.zh-CN.md
docs/CLUSTER_DEV_LOCAL_COMMON_BUILD.zh-CN.md
docs/FULL_RELEASE_UPGRADE_PREFLIGHT_20260929.zh-CN.md
docs/openapi/README.zh-CN.md
docs/openapi/crypto-openapi-v1.yaml
docs/CRYPTO_OPEN_API_V1.zh-CN.md
docs/DC_OPEN_API_V1_REFERENCE.zh-CN.md
```

深入集群时再读 `ORDER_CLUSTER_*`、`TRADE_CLUSTER_*`、`MD_CLUSTER_*`、`ROBOT_*`、`WEBSOCKET_*`。

---

## 21. 新账号 / 新会话接手步骤

可直接把下面内容给新会话：

```text
先读取 dc-quant-deploy/OPEN_TRADING_CORE_HANDOFF.md，
再读取 docs/openapi/README.zh-CN.md 和当前任务相关架构/验收文档。

不要先改代码。

第一步：
1. 检查所有相关仓库 branch/status；
2. fetch 最新远端；
3. 查看是否有其它会话新提交；
4. 确认当前 Docker 容器实际 Image ID / Git revision；
5. 报告当前状态和将修改的仓库；
6. 只在最新合并代码上开发；
7. 不 force push；
8. 正式镜像统一通过 GitHub Actions 完整构建；
9. 发布后必须运行 Playwright / E2E。
```

---

## 22. 源码总清单

```text
01  bliplink/com.app.dc.ordersvr
02  bliplink/com.app.dc.tradesvr
03  bliplink/com.app.dc.projectionsvr
04  bliplink/com.app.dc.mdsvr
05  bliplink/com.app.dc.liqsvr
06  bliplink/com.app.dc.robotsvr
07  bliplink/gw
08  bliplink/com.app.dc.adminsvr
09  bliplink/com.app.dc.managersvr
10  bliplink/com.app.dc.loginsvr
11  bliplink/com.app.dc.apssvr
12  bliplink/com.app.common
13  bliplink/gateway-api
14  bliplink/dc-trade-web
15  bliplink/dc-saas-tenant-web
16  bliplink/dc-saas-platform-web
17  bliplink/opentradingcore-web
18  bliplink/dc-quant-deploy
19  TradingView 稳定版本源 / 依赖
```

---

## 23. 当前接手最重要的三件事

1. **先修 Trade Web 黑屏，但必须从最新合并 Git 完整构建，不再做 index/JS/CSS 拼接。**
2. **恢复 GitHub Actions 正常发布能力，把 Web 镜像统一改成 Actions 完整构建/发布。**
3. **任何新会话开始前先读本文，先 fetch/rebase，再动代码。**
