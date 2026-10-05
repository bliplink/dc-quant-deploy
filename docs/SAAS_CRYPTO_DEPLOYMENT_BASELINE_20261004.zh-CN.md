# OpenTradingCore SaaS Crypto 部署与代码基线

> 日期：2026-10-04  
> 适用分支：`saas-crypto`  
> 适用目标：第二轮全新环境部署、HA 验收、正式发布交接  
> 部署仓库：`bliplink/dc-quant-deploy`

## 1. 文档目的

本文是 OpenTradingCore SaaS Crypto 当前代码、镜像和部署关系的 Source of Truth 之一，用于回答以下问题：

- 每个组件的代码在哪个 GitHub 仓库；
- 正式发布使用哪个分支；
- 每个仓库负责什么；
- 哪些仓库会产出 Docker 镜像，镜像名称是什么；
- 哪些仓库属于 Maven / 共享代码依赖，不直接部署；
- `dc-quant-deploy` 如何锁定一轮完整发布；
- 主站、Trade Web、Tenant Web、Platform Web、API Docs 分别如何部署；
- Order / Trade HA 验收时涉及哪些节点和端口；
- 第二轮验证为什么不得依赖 `local/*` 镜像或本地未提交代码。

本文记录的 commit / image tag 是 **2026-10-04 第二轮验证前的已发布基线**。以后代码继续前进时，发布流程仍按本文的规则执行，但 release-lock 中的具体 SHA 应同步更新。

---

## 2. 统一发布原则

### 2.1 唯一正式分支

所有正式组件统一使用：

```text
saas-crypto
```

规则：

1. 第二轮验证只认 GitHub 远端 `saas-crypto`；
2. `main`、feature、tmp、cluster-dev、本地 worktree 均不得直接作为正式部署源；
3. 有效生产改动必须先进入对应仓库 `saas-crypto`；
4. `saas-crypto HEAD` 必须有对应的成功 GitHub Actions；
5. 可部署组件必须由 Actions 发布 GHCR 镜像；
6. 正式验证只使用 immutable `sha-*` tag，不使用浮动 tag 作为验收基线；
7. 可部署镜像必须同时支持：
   - `linux/amd64`
   - `linux/arm64`
8. 正式第二轮验证禁止使用：
   - `local/*`
   - 仅存在本机 Docker cache、但未发布到 GHCR 的镜像
   - 本机未提交代码构建的镜像
   - 未进入 `saas-crypto` 的代码

### 2.2 发布锁

完整发布镜像清单由以下文件固定：

```text
release/saas-crypto-images.env
```

静态门禁：

```text
tests/test-release-image-lock.sh
```

当前要求：

```text
IMAGE_SOURCE=registry
所有镜像仓库必须是 ghcr.io/bliplink/*
所有发布 tag 必须是 sha-*
不得引用 local/*
不得用浮动 saas-crypto tag 作为第二轮固定发布镜像
```

`release/saas-crypto-images.env` 是第二轮环境重建时的镜像 Source of Truth。

---

## 3. 代码仓库总表

推荐本地 checkout 统一放在：

```text
$WORKSPACE/<repository-name>
```

实际 Source of Truth 是 GitHub 仓库，不依赖某台机器的绝对本地路径。

### 3.1 基础依赖与框架

| GitHub 代码路径 | 分支 | 当前 HEAD | 作用 | 发布方式 |
|---|---|---|---|---|
| `bliplink/com.app.common` | `saas-crypto` | `6eb9e28672cd787753f576f4b13cafbecadd9cb4` | 通用模型、工具、共享基础代码 | 发布 Maven Central；当前正式依赖线为 Common 3.0.15 |
| `bliplink/com.app.dc` | `saas-crypto` | `876a4abd026fdea4c5e48823fcb431fbb57925f2` | DC 服务共享业务框架；引用 Common | 不单独部署；各服务构建时 clone / build |
| `bliplink/gateway` | `saas-crypto` | `b541f70f6da8cdedb84fed3925a96190f2658785` | Gateway library / 通信共享层 | 库依赖；不作为 SaaS 业务容器单独部署 |

固定依赖方向：

```text
com.app.common
    ↓
com.app.dc
    ↓
各 DC 服务仓库

com.app.common / gateway library
    ↓
gw
```

禁止为了单个服务临时改变这条正式发布架构。

### 3.2 后端服务

| GitHub 代码路径 | 分支 | 当前 HEAD | 服务职责 | GHCR 镜像 |
|---|---|---|---|---|
| `bliplink/gw` | `saas-crypto` | `6a84739d2149da0eaaf1ea64f485a2a19843f78d` | 统一 TCP / WebSocket / HTTP Gateway、服务路由、Session | `ghcr.io/bliplink/gw:sha-6a84739` |
| `bliplink/com.app.dc.loginsvr` | `saas-crypto` | `9fdaf39deda7f5e8405bfd1c891a60f4d29314cf` | 登录、Session、身份认证 | `ghcr.io/bliplink/loginsvr:sha-9fdaf39` |
| `bliplink/com.app.dc.mdsvr` | `saas-crypto` | `d91d3b7830065ad049a3ff75e7ede045192658c5` | 行情、订单簿、Kline、市场数据集群 | `ghcr.io/bliplink/mdsvr:sha-d91d3b7` |
| `bliplink/com.app.dc.apssvr` | `saas-crypto` | `73e3fd518de951ed57874b625d6ef1da793541ed` | 外部价格源 / mark price / Binance 等市场源 | `ghcr.io/bliplink/apssvr:sha-73e3fd5` |
| `bliplink/com.app.dc.ordersvr` | `saas-crypto` | `4f9feaa23c5297229bf84354b96df8afc8747b9d` | 下单、撤单、撮合入口、Order HA 分区状态 | `ghcr.io/bliplink/ordersvr:sha-4f9feaa` |
| `bliplink/com.app.dc.projectionsvr` | `saas-crypto` | `2d54c9d3234b948a8ed0a61e9b05c22b499d6f5a` | Order / Trade projection、查询侧状态与 watermark | `ghcr.io/bliplink/projectionsvr:sha-2d54c9d3234b948a8ed0a61e9b05c22b499d6f5a` |
| `bliplink/com.app.dc.tradesvr` | `saas-crypto` | `d0265ca8c617dffbd9181bfe02f89eea364df655` | 资金、持仓、执行结果、Trade HA、journal/archive catch-up | `ghcr.io/bliplink/tradesvr:sha-d0265ca8c617dffbd9181bfe02f89eea364df655` |
| `bliplink/com.app.dc.liqsvr` | `saas-crypto` | `5df0879f7783311fcf02336e7135bcedb06a8d04` | 风控清算、强平相关业务 | `ghcr.io/bliplink/liqsvr:sha-5df0879f7783311fcf02336e7135bcedb06a8d04` |
| `bliplink/com.app.dc.managersvr` | `saas-crypto` | `938a3776b5aca7a09baad3a6de09be363a79a081` | 平台控制面、租户申请、自动审批、试用 bootstrap | `ghcr.io/bliplink/managersvr:sha-938a3776b5aca7a09baad3a6de09be363a79a081` |
| `bliplink/com.app.dc.adminsvr` | `saas-crypto` | `0409add2495da84c51e3d46cbfefa3b4c3d7ec58` | Tenant Admin 控制面：用户、配置、Robot、查询、租户管理 | `ghcr.io/bliplink/adminsvr:sha-0409add2495da84c51e3d46cbfefa3b4c3d7ec58` |
| `bliplink/com.app.dc.robotsvr` | `saas-crypto` | `abd7efa1ffa7921f8c384f92c09f25c46419f63b` | Demo/租户流动性 Robot、自动报价、订单补充 | `ghcr.io/bliplink/robotsvr:sha-abd7efa1ffa7921f8c384f92c09f25c46419f63b` |

### 3.3 Web 与文档站

| GitHub 代码路径 | 分支 | 当前 HEAD | 作用 | GHCR 镜像 | 本机端口 |
|---|---|---|---|---|---:|
| `bliplink/dc-trade-web` | `saas-crypto` | `9cb34fe3361026b40ce7f57903012bf152057631` | 最终 Trader 交易 Web | `ghcr.io/bliplink/dc-saas-trade-web:sha-9cb34fe3361026b40ce7f57903012bf152057631` | 18088 |
| `bliplink/dc-saas-platform-web` | `saas-crypto` | `9cecccce383c7d6e87649b8a10b0b1f4ac4f0f8c` | Platform 管理后台 | `ghcr.io/bliplink/dc-saas-platform-web:sha-9cecccce383c7d6e87649b8a10b0b1f4ac4f0f8c` | 18090 |
| `bliplink/dc-saas-tenant-web` | `saas-crypto` | `5ad8a568cfdb974284c15e94b1ec41d3a2aa2311` | Tenant Portal：创建/登录租户与 Tenant Admin 控制台 | `ghcr.io/bliplink/dc-saas-tenant-web:sha-5ad8a568cfdb974284c15e94b1ec41d3a2aa2311` | 18092 |
| `bliplink/opentradingcore-web` | `saas-crypto` | `e4d98b190ce520223d1208196eb16e8cec2887d7` | `opentradingcore.com` 对外主站、产品介绍与入口 | `ghcr.io/bliplink/opentradingcore-web:sha-e4d98b190ce520223d1208196eb16e8cec2887d7` | 18094 |
| `bliplink/opentradingcore-api-docs` | `saas-crypto` | `9d739c30646b28249a9685c38a0d7633f16c11ee` | `api.opentradingcore.com` API Docs / OpenAPI / 中英文开发文档 | `ghcr.io/bliplink/opentradingcore-api-docs-web:sha-9d739c30646b28249a9685c38a0d7633f16c11ee` | 18096 |

所有上表 Web 镜像的当前正式构建都必须是：

```text
linux/amd64
linux/arm64
```

主站和 API Docs 已独立为自己的代码仓库与发布流水线，不再依赖本机手工镜像。

### 3.4 部署仓库

| GitHub 代码路径 | 分支 | 2026-10-04 发布基线 | 作用 |
|---|---|---|---|
| `bliplink/dc-quant-deploy` | `saas-crypto` | `c33d3e43a7f7b20dd280e5cda98a269765e39b77`（本文档提交前） | Compose、环境模板、DB migrations、ZK assignment、部署/验证/验收脚本、16 项 release-lock |

本文档合并后 `dc-quant-deploy/saas-crypto` HEAD 会自然前进；镜像 release-lock 不应因为文档提交而改变。

---

## 4. API Docs 代码归属规则

从 2026-10-04 起，API Docs 的唯一编辑源为：

```text
bliplink/opentradingcore-api-docs
branch: saas-crypto
```

该仓库负责：

- `docs/public-api`
- `docs/openapi`
- `docs/api`
- MkDocs 配置
- OpenAPI catalog 生成
- 中英文一致性校验
- API Docs Dockerfile
- `linux/amd64 + linux/arm64` GHCR 发布

发布镜像：

```text
ghcr.io/bliplink/opentradingcore-api-docs-web:sha-<commit>
```

`dc-quant-deploy` 只负责：

- 通过 release-lock 选择 API Docs 镜像；
- `docker compose` 启动 `api-docs`；
- 18096 healthcheck；
- 本地 / 公网部署验收。

### 4.1 迁移遗留说明

`dc-quant-deploy` 中目前仍可能存在 `docs/public-api`、`docs/openapi`、旧 API Docs build/publish workflow 等迁移前文件。它们属于迁移遗留，不再作为 API Docs 内容编辑 Source of Truth。

新文档内容必须优先提交到：

```text
bliplink/opentradingcore-api-docs/saas-crypto
```

后续可在单独清理 PR 中删除 deployment 仓库里的旧 build/publish 职责，避免同一份文档双写。

---

## 5. `dc-quant-deploy` 关键路径

| 路径 | 用途 |
|---|---|
| `compose.yaml` | 生产 SaaS 主 Compose；当前包含后端、业务 Web、主站、API Docs |
| `.env.example` | 环境变量模板，不得保存生产 secret |
| `.env.prod` | 运行机本地生产环境文件，不提交 Git |
| `release/saas-crypto-images.env` | 16 项正式镜像 immutable release-lock |
| `deploy-saas.sh` | 主部署脚本；生产 Linux 主机的正式入口 |
| `generate-saas-configs.sh` | 生成运行时配置 |
| `validate-saas.sh` | 部署后基础健康与配置验证 |
| `acceptance-saas.sh` | 统一业务验收入口 |
| `auto-update-saas.sh` | 浮动环境的自动更新机制；第二轮固定 SHA 验收期间不应改变 release-lock |
| `mysql/migrations/` | MySQL schema migration |
| `clickhouse/migrations/` | ClickHouse migration |
| `control.prod/` | 集群控制配置、placement 等模板 |
| `tests/` | Order / Trade / MDS / tenant / release 等验收与回归测试 |

重要约束：

```text
第二轮验证环境以 release/saas-crypto-images.env 为镜像基线，
而不是依赖 .env.example 中默认的浮动 saas-crypto tag。
```

---

## 6. 当前 16 项正式镜像

截至本文档基线，第二轮必须使用以下 16 项 GHCR 镜像：

| 组件 | Immutable image |
|---|---|
| Gateway | `ghcr.io/bliplink/gw:sha-6a84739` |
| LoginSvr | `ghcr.io/bliplink/loginsvr:sha-9fdaf39` |
| MDSvr | `ghcr.io/bliplink/mdsvr:sha-d91d3b7` |
| APSSvr | `ghcr.io/bliplink/apssvr:sha-73e3fd5` |
| OrderSvr | `ghcr.io/bliplink/ordersvr:sha-4f9feaa` |
| ProjectionSvr | `ghcr.io/bliplink/projectionsvr:sha-2d54c9d3234b948a8ed0a61e9b05c22b499d6f5a` |
| TradeSvr | `ghcr.io/bliplink/tradesvr:sha-d0265ca8c617dffbd9181bfe02f89eea364df655` |
| LiqSvr | `ghcr.io/bliplink/liqsvr:sha-5df0879f7783311fcf02336e7135bcedb06a8d04` |
| ManagerSvr | `ghcr.io/bliplink/managersvr:sha-938a3776b5aca7a09baad3a6de09be363a79a081` |
| AdminSvr | `ghcr.io/bliplink/adminsvr:sha-0409add2495da84c51e3d46cbfefa3b4c3d7ec58` |
| RobotSvr | `ghcr.io/bliplink/robotsvr:sha-abd7efa1ffa7921f8c384f92c09f25c46419f63b` |
| Trade Web | `ghcr.io/bliplink/dc-saas-trade-web:sha-9cb34fe3361026b40ce7f57903012bf152057631` |
| Tenant Web | `ghcr.io/bliplink/dc-saas-tenant-web:sha-5ad8a568cfdb974284c15e94b1ec41d3a2aa2311` |
| Platform Web | `ghcr.io/bliplink/dc-saas-platform-web:sha-9cecccce383c7d6e87649b8a10b0b1f4ac4f0f8c` |
| Public Web | `ghcr.io/bliplink/opentradingcore-web:sha-e4d98b190ce520223d1208196eb16e8cec2887d7` |
| API Docs | `ghcr.io/bliplink/opentradingcore-api-docs-web:sha-9d739c30646b28249a9685c38a0d7633f16c11ee` |

其中主站当前双架构 manifest list：

```text
sha256:c0366c38395f08b5178fac9a68af2108bdb5bbf8c129e7f4a56ed30160c857b9
```

API Docs 当前双架构 manifest list：

```text
sha256:9f1f81370556f6ad1cbb7e0394e4862b9424402df587e32e1501bd42a66b26cb
```

---

## 7. 端口与入口

### 7.1 基础设施

| 服务 | Host port |
|---|---:|
| ZooKeeper | 32181 |
| MySQL | 33306 |
| ClickHouse HTTP | 38123 |
| ClickHouse Native | 39000 |

### 7.2 Gateway

| 接口 | Host port |
|---|---:|
| GW TCP | 33000 |
| GW WebSocket | 33001 |
| GW HTTP | 33002 |

统一 HTTP 业务入口：

```text
POST /api
POST /httpapi/
```

### 7.3 后端服务端口

| 服务/节点 | Port |
|---|---:|
| LoginSvr HTTP | 33990 |
| LoginSvr GW | 33034 |
| MDSvr A | 33028 |
| MDSvr B | 33043 |
| MDSvr C | 33045 |
| APSSvr | 33035 |
| OrderSvr A | 33036 |
| OrderSvr B | 33041 |
| OrderSvr C | 33044 |
| ProjectionSvr | 33042 |
| TradeSvr A | 33037 |
| TradeSvr B | 33046 |
| LiqSvr | 33038 |
| ManagerSvr | 33039 |
| AdminSvr | 33040 |

Order replication：

```text
A 19121
B 19122
C 19123
```

Trade replication：

```text
A 19221
B 19222
```

### 7.4 Web

| 网站 | Container/service | Host port | 公网入口 |
|---|---|---:|---|
| Trade Web | `dc-saas-trade-web` / `web` | 18088 | `trade.opentradingcore.com` |
| Platform Web | `dc-saas-platform-web` / `platform-web` | 18090 | `platform.opentradingcore.com` |
| Tenant Web | `dc-saas-tenant-web` / `tenant-web` | 18092 | `tenant.opentradingcore.com` |
| Public Web | `dc-saas-public-web` / `public-web` | 18094 | `opentradingcore.com` / `www.opentradingcore.com` |
| API Docs | `dc-saas-api-docs` / `api-docs` | 18096 | `api.opentradingcore.com` |

Cloudflare Tunnel 只负责公网 ingress；服务是否健康必须先以本机 origin 为准。

例如公网主站 `/httpapi/` 返回 502 时，应先检查：

```text
127.0.0.1:18094
    ↓ nginx reverse proxy
127.0.0.1:33002
    ↓ Gateway
AdminSvr / ManagerSvr / OrderSvr / ...
```

Tunnel 在线不代表 Gateway 一定在线。

---

## 8. Order / Trade HA 部署拓扑

### 8.1 Order

正式 HA：

```text
OrderSvrA
OrderSvrB
OrderSvrC
```

核心特征：

- 256 partitions；
- ZooKeeper 保存 assignment / epoch / state；
- 自动 primary promotion；
- A/B/C 三副本相关部署逻辑由 `dc-quant-deploy` 固定；
- 第二轮验收必须动态找到业务 partition 的真实 Primary，再做 `SIGKILL`；
- 不允许写死“总是杀 A”或“总是杀 B”。

验收重点：

```text
真实下单/撤单/撮合
→ SIGKILL current primary
→ ZK primary change
→ READY
→ Gateway/API 恢复
→ 挂单/执行不丢
→ 无 duplicate fill
→ 无 split brain
→ old primary restart
→ catch-up / replica rejoin
```

### 8.2 Trade

正式 HA：

```text
TradeSvrA
TradeSvrB
```

当前镜像 `d0265ca...` 包含 archive + active journal catch-up 逻辑。

第二轮必须覆盖：

```text
建立真实持仓
→ 产生 journal / archive history
→ SIGKILL current primary
→ 自动 promotion
→ 持仓/余额/执行状态不丢
→ old node restart
→ 跨 archive + active journal catch-up
→ role reversal
→ recovered node 可再次成为 primary
→ reduce-only 平仓
→ 最终 position = 0
```

---

## 9. 租户控制面与自动流动性

控制面职责：

```text
ManagerSvr
  ├─ tenant application
  ├─ automatic approval
  └─ trial liquidity bootstrap orchestration

AdminSvr
  ├─ tenantBootstrap
  ├─ tenantUserAdmin
  ├─ tenantSettingsAdmin
  ├─ tenantRobotAdmin
  └─ tenant management/query methods

RobotSvr
  └─ tenant demo liquidity / quote replenishment
```

Fresh deployment 必须包含 MySQL migration：

```text
dc_tenant_liquidity_bootstrap
```

`deploy-saas.sh` 在业务服务启动前必须执行 schema verification gate。

Fresh trial tenant 基线应验证：

```text
Application = APPROVED / AUTO_APPROVAL
bootstrap = COMPLETE
Robot = RUNNING
open_order_count = 40
bid/ask = 20 + 20
public book 至少可见 10 + 10
```

---

## 10. 正式构建和发布流程

### 10.1 后端服务

标准过程：

```text
修改 <service>/saas-crypto
→ commit + push GitHub
→ GitHub Actions build
→ GHCR linux/amd64 + linux/arm64
→ 得到 sha-<commit> tag
→ 更新 dc-quant-deploy/release/saas-crypto-images.env
→ deployment CI
→ clean deploy / acceptance
```

不得直接：

```text
本地改代码
→ docker build local/...
→ 直接进入第二轮正式验收
```

### 10.2 Common / com.app.dc

固定流程：

```text
com.app.common
→ 发布 Maven Central 新版本
→ com.app.dc 引用该版本
→ 服务 Actions clone/build com.app.dc
→ 产服务 GHCR 镜像
```

`com.app.dc` 不单独作为生产服务发布。

### 10.3 Public Web

```text
bliplink/opentradingcore-web
branch: saas-crypto
→ GitHub Actions
→ ghcr.io/bliplink/opentradingcore-web:sha-<commit>
→ 更新 release-lock
→ dc-quant-deploy public-web
```

### 10.4 API Docs

```text
bliplink/opentradingcore-api-docs
branch: saas-crypto
→ bilingual/OpenAPI validation
→ MkDocs build
→ multi-arch Docker build
→ ghcr.io/bliplink/opentradingcore-api-docs-web:sha-<commit>
→ 更新 release-lock
→ dc-quant-deploy api-docs
```

---

## 11. 新机器 / 第二轮验证部署规则

第二轮验证的目标是证明：

> 一台不依赖历史本地镜像的新机器，只要拿到 `dc-quant-deploy/saas-crypto`、运行 secret 和 GHCR 网络访问能力，就可以完整重建系统。

推荐流程：

```bash
git clone https://github.com/bliplink/dc-quant-deploy.git
cd dc-quant-deploy
git checkout saas-crypto

cp .env.example .env.prod
# 写入真实 secret，不提交 .env.prod

# 将 release/saas-crypto-images.env 中镜像项覆盖到 .env.prod
# IMAGE_SOURCE 必须为 registry

docker compose --env-file .env.prod -f compose.yaml config --quiet
docker compose --env-file .env.prod -f compose.yaml pull
```

生产 Linux 主机使用正式部署脚本：

```bash
sudo ENV_FILE="$PWD/.env.prod" ./deploy-saas.sh --full-cluster
```

不得为了通过正式验收而修改 `deploy-saas.sh` 的生产逻辑。

部署完成后：

```bash
./validate-saas.sh
./acceptance-saas.sh
```

并额外执行本轮定义的 Order / Trade HA 故障注入。

---

## 12. 第二轮验收顺序

固定顺序：

1. **Fresh infrastructure**
   - MySQL
   - ClickHouse
   - ZooKeeper
   - migrations
   - schema gates
2. **镜像与版本核对**
   - 16 项全部来自 release-lock
   - 无 `local/*`
   - running image 与 immutable tag 对应
3. **Web / 公网入口**
   - Public Web 18094
   - API Docs 18096
   - Trade 18088
   - Platform 18090
   - Tenant 18092
   - Gateway `/httpapi/`
4. **Order clean genesis**
   - 256/256 READY
5. **Trade clean genesis**
   - 256/256 READY
6. **Tenant bootstrap**
   - auto approval
   - bootstrap COMPLETE
   - Robot RUNNING/40
7. **Normal trading E2E**
   - register/login
   - cashIn
   - Limit / IOC
   - cancel
   - match
   - reduce-only close
8. **Order HA**
   - live load
   - dynamic primary
   - SIGKILL
   - promotion / recovery / catch-up
9. **Trade HA**
   - held position
   - SIGKILL
   - archive catch-up
   - role reversal
10. **Authoritative consistency**
    - MySQL orders / executions
    - balances
    - positions
    - open orders
    - Projection watermark
    - Trade state
    - Robot state
11. **最终 flat**
    - 测试 trader position = 0
    - active orders = 0

---

## 13. 发布前必须核对的门槛

每次完整正式发布至少核对：

```text
[ ] 所有相关代码已 push 到 GitHub
[ ] 所有正式代码位于 saas-crypto
[ ] saas-crypto HEAD 与最新成功 Actions head_sha 一致
[ ] 16 项可部署镜像已发布 GHCR
[ ] 16 项镜像均支持 linux/amd64 + linux/arm64
[ ] release-lock 已更新为 immutable sha-*
[ ] release-lock 中不存在 local/*
[ ] release-lock test PASS
[ ] docker compose config PASS
[ ] 新机器可 docker compose pull
[ ] deployment CI SUCCESS
[ ] 不存在“只在本机生效”的生产补丁
```

---

## 14. 不应进入正式发布的内容

以下内容允许作为开发/诊断材料存在，但不能被当作正式第二轮基线：

- `.tmp-*`
- feature worktree 中未合并代码
- local Docker image
- 手工 patch 后未 commit 的代码
- 旧 cluster-dev 镜像
- 旧数据损坏的现场修复脚本
- 只在某一台 Mac 上存在的运行文件

历史数据损坏与正式代码健康是两个不同问题。第二轮采用 fresh data，因此旧环境数据问题不得通过把本地补丁偷偷带进新环境的方式处理。

---

## 15. 当前发布职责边界

```text
GitHub saas-crypto source
        ↓
GitHub Actions
        ↓
Maven Central / GHCR
        ↓
dc-quant-deploy release-lock
        ↓
docker compose / deploy-saas.sh
        ↓
local origins
        ↓
Cloudflare Tunnel
        ↓
public hostnames
```

其中：

- **源码仓库** 决定代码；
- **Actions** 决定构建物；
- **GHCR/Maven Central** 保存正式发布产物；
- **dc-quant-deploy** 决定本轮使用哪一组产物；
- **Cloudflare** 只负责公网 ingress，不是业务服务健康 Source of Truth。

---

## 16. 维护规则

当新增组件时，必须同步更新：

1. 本文仓库表；
2. `.env.example`；
3. `compose.yaml`；
4. `release/saas-crypto-images.env`；
5. `tests/test-release-image-lock.sh`；
6. `validate-saas.sh`；
7. 必要的 acceptance；
8. GitHub Actions 多架构发布。

当删除组件时也必须同时清理以上路径，避免出现“代码已经不用，但 deployment 仍然拉镜像”的幽灵依赖。

本文档应在发布架构、仓库拆分、端口、镜像名称或正式分支策略发生变化时同步更新。
