# 租户产品与独立数据源｜直接外键实现记录（2026-10-19）

## 用户确认的简化关系

**不创建产品与数据源的中间关联表。** 当前产品表使用 `dc_tenant_symbol`，增加 `data_source_id` 和独立显示名 `product_name`，与新表 `dc_tenant_data_source` 直接关联：

```text
  dc_tenant_data_source                         dc_tenant_symbol
  ├─ location            ◄──────────────────── ├─ location
  ├─ data_source_id      ◄────────────┐         ├─ security_id（租户产品代码）
  ├─ source_name                       │         ├─ product_name（产品显示名）
  ├─ source_type BINANCE / CUSTOM      └─────── ├─ data_source_id（可空外键）
  ├─ source_symbol（外部指标标识）                 ├─ tick_size / qty_tick_size / ...
  ├─ enabled                                    └─ enabled
  └─ config_json
```

- 数据源表主键 `(location,data_source_id)`，产品表组合外键 `(location,data_source_id)`，**数据库层拒绝跨租户引用**。
- 一个数据源被多个产品复用；一个产品至多绑定一个数据源。**产品代码独立于外部价格源代码**，例：`BTCUSDT` 与 `BTC001USDT` 可绑定同一个 Binance `BTCUSDT` 来源。
- 原有产品 `data_source_id=NULL`，保持旧行情路由。新增自定义产品以 `enabled=0` **草稿**保存，不会自动进入撮合、MD、资金费率、风险和强平。
- 源表不存明文密钥，当前 `config_json` 仅保留扩展字段；支持 Binance 和租户自定义来源定义，实际数据订阅适配尚未完成。
- 租户管理 API Key 改为两个 Tab：租户 API Key 与用户 API Key；Robot 使用**普通用户 Key**，关联/用途只作为备注显示，不创建 Robot Key 类型。

## 已提交代码（全部 `saas-crypto`）

1. `bliplink/dc-quant-deploy/mysql/migrations/20261019_tenant_product_data_source.sql`：独立数据源定义表、产品名称及外键；提交 `a3b953a`、`cc274d4`。
2. `bliplink/com.app.dc.adminsvr/src/main/java/com/app/dc/handler/TenantDataSourceAdminHandler.java`：租户身份校验的 `tenantDataSourceAdmin` `LIST/CREATE/UPDATE/DELETE`，已绑定数据源禁止删除/变更关键来源；`91d3244`。
3. `bliplink/com.app.dc.adminsvr/src/main/java/com/app/dc/handler/TenantProductDataSourceHandler.java`：租户身份校验的 `tenantProductDataSource` `LIST/CREATE_DRAFT/BIND/UNBIND`。产品创建仅元数据草稿、通过外键直接绑定租户来源；`3cdc18f`、`60a5cb5`。
4. `bliplink/dc-saas-tenant-web/src/ApiKeys.jsx`：两个 Tab，移除 Robot 独立 Tab，Robot 用途归到普通用户 Key 表；`c7a69c`。
5. `bliplink/dc-saas-tenant-web/src/DataSources.jsx`：数据源列表、查询、创建和维护；`55155e8`。
6. `bliplink/dc-saas-tenant-web/src/Symbols.jsx`：更名为产品管理，展示数据源绑定、创建独立代码停用草稿、`BIND/UNBIND`；`7a620d2`。
7. `bliplink/dc-saas-tenant-web/src/main.jsx`：新增数据源管理导航、产品管理入口；`c398403`。

## Mac mini 实际验证结果

- **真实迁移已应用**到 Demo MySQL。部署前 `dc_tenant_symbol` 的 DDL 已备份在 `~/.opentradingcore/broker-v1-demo-checkpoints-20261018/tenant-product-schema-before-source-20261019.sql`。迁移表与 `product_name/data_source_id` 字段，以及 `fk_tenant_product_data_source` 外键存在；旧数据未回填。
- 在真实 MySQL 的**事务内**创建 GW7XMI Binance BTCUSDT 来源，`BTCUSDT` 与 `BTC001USDT` 两个产品绑定同一个数据源，结果引用数 **2**，然后 `ROLLBACK`；检查来源与草稿行仍为 **0**。
- 将 GW7XMI 来源尝试绑定到 H00000 产品，真实 MySQL **外键拒绝 ERROR 1452**；断线回滚，来源数仍为 0，**跨租户约束通过**。
- AdminSvr Mac JDK8 本地编译 **171 源文件，BUILD SUCCESS**；本地全量测试 **74 项、0 fail/error、1 skipped**（注意这些是既有测试，新源码的正式登录管理场景尚未 E2E）。
- Tenant Web Vite 8 本地 **30 modules transformed, build successful**。构建后的静态 bundle 已生成。
- **镜像构建/现网替换未执行成功**：WebCodex 在尝试执行包含 Dockerfile 的本地构建命令时直接返回 `Script error: 此工具调用被 OpenAI 的安全检查屏蔽。请仔细检查你发送的内容。`。现网 AdminSvr 仍为 `local/dc-saas-adminsvr:broker-v1-staging-beanfix-20261018`；租户 Web 仍为原 GHCR `sha-c44ce47...`。不得将“本地编译通过”误报为“新管理页面已部署上线”。
- 部署后续仍需要开启合法 TenantAdmin 管理会话，对 `CREATE→BIND→LIST→UPDATE→DELETE/解绑` 进行正向 API E2E；当前只做了 MySQL 事务及匿名鉴权验证。不要读取或借用 Robot 两把 Trader Key 代替 Tenant API。
- 现有 GW7XMI `BTCUSDT` 产品仍 `enabled=1,data_source_id=NULL,product_name=NULL`，Robot `RUNNING/40`；现有 Demo `BROKER_PRICE_PUBLISH_ENABLED=false`，三台 MD 的 Broker 接收/路由/转发仍 OFF。**未改变任何实际订单、资金、行情或强平路径**。

## 2026-10-19 追加确认：MdSvr 仅消费 AdminSvr Symbol（强制架构约束）

- **AdminSvr 是产品与数据源绑定关系的唯一配置组装方。** AdminSvr 从 `dc_tenant_symbol` 与 `dc_tenant_data_source` 取得关联信息，在既有 Symbol 数据下发路径中携带来源字段（租户 location、产品 security_id、data_source_id、source_type、source_symbol、来源是否可用及必要的价格路由元数据）。
- **MdSvr 只依赖既有 AdminSvr → MdSvr Symbol 获取/刷新机制。** MdSvr 禁止新增数据源表 SQL 读取、独立配置文件、额外 AdminSvr 数据源配置 RPC/订阅或第二套配置缓存。价格处理所需的来源映射只从现有 Symbol 快照/增量数据派生到内存索引，不能把运行时内存索引误当成另一份配置来源。
- 价格数据可沿既有 APS → MdSvr 报价链路流入。MdSvr 基于 `(location, data_source_id)` 或等价的已下发 Symbol 字段完成来源到多个产品的路由，再使用**产品自己的 security_id**发布行情；外部 source_symbol 不能直接作为交易产品代码。
- `data_source_id=NULL` 的历史产品继续原有价格路径；未启用的自定义产品不得进入交易/强平。配置变更必须通过现有 Symbol 更新流程，进行版本/顺序校验和原子映射切换；新来源没有有效价格时不可沿用旧来源缓存值。
- **实现前核对原有 Symbol 的具体数据结构和 MdSvr 的既有接收入口**，只对这些既有接口做向后兼容扩展；不要凭本文臆造新接口或配置通道。AdminSvr 需维持已有订阅/重新订阅快照语义。
- 端到端验收至少覆盖：同租户两个不同产品复用同一 Binance 来源；自定义来源 Broker 发布；跨租户隔离；动态重绑定无旧价格穿透；旧产品兼容；Trade/Liq 消费产品价格；故障重订阅后映射重建。任何未完成的项目均不得标成“已上线”。

## 正式生效仍需后续集成

1. 部署新 Admin/Web 镜像并跑带授权租户的 CRUD 验收、禁用/解绑/跨租户拒绝、审计与回滚。
2. **交易核心产品注册**：旧 `dc_symbol` 是全局产品表，Order/Trade/MD 多处依赖它。草稿 `BTC001USDT` 尚不能交易，必须把租户独立产品的交易规则完整传递给 Order/Trade/MD、风控与 Projection，才能启用。
3. **MD 价格路由与引用扩散**：按租户和 `data_source_id` 找到来源实际行情代码（如 Binance BTCUSDT），价格映射后按产品代码 `BTC001USDT` 发布给原有 Trade/Liq；一个来源可扇出多个产品，不能把来源标识当产品标识。
4. **APS 自定义报价**：继续使用租户 API Key 的 TenantAPI 会话身份防串租户，不要求 `PRICE_PUBLISH` 额外权限；产品/来源配置启用前不影响 Binance 原路径。实际 Broker 发布 E2E 和强平、资金风险回归完成后，才可打开相应价格功能开关。

**总判定：数据模型、后台元数据接口、前端页面源码及本地编译已完成；Demo 数据库迁移已应用；新页面未部署，实际自定义产品交易/价格数据源路由尚未验收。**

## 统一交付方案：租户产品、数据源、Broker API、SDK、Demo 验收（2026-10-19）

### 目标及禁止项

本轮**一条完整交付链**，不再增加中间关系表或为 MD 单独设计配置系统。核心逻辑：租户可定义任意产品代码，绑定本租户一个数据源（多产品可共享来源）；接收 Binance 或 Broker 发布的指数价/标记价，MD 按 AdminSvr 提供的 Symbol 映射到产品，沿原有交易与风控/强平链路使用。旧产品保持兼容。不可仅以 UI CRUD 成功视为交易功能完成。

- 数据模型固定：`dc_tenant_symbol(location,security_id,data_source_id,...)` 关联 `dc_tenant_data_source(location,data_source_id,source_type,source_symbol,...)`；拒绝跨租户绑定。
- AdminSvr 作为 Symbol 数据的唯一配置提供方，对既有 Symbol 下发结构作兼容扩展，组装产品规则、来源关联及必要启用状态；MD 只能消费现有 AdminSvr→MD Symbol 快照/更新，不查库、不读取独立配置、不新增第二套同步路径。
- APS 负责接收并提供来源价格，Broker API 的发布操作使用真实租户身份；MD 负责来源价→租户产品价映射和扇出；Order/Trade/Liq/Projection 只按交易产品身份处理业务，不将 source_symbol 当成 security_id。
- 暂不启用未端到端验证的自定义产品；无有效价格或切换中采用阻断/不就绪，**禁止使用之前来源的旧价格**；保持现有租户和 robot 的行情与交易路径不变。

### 开发顺序与验收门槛

**阶段 A — 管理页面上线及 E2E（优先）**

核对现有 AdminSvr 与 Tenant Web 镜像和本地构建产物，优先本地编译、替换 Demo 镜像（目前 GitHub Actions 额度不足）。验收有效租户身份下数据源 LIST/CREATE/UPDATE/DELETE、产品 CREATE_DRAFT/BIND/UNBIND、已绑定来源变更与删除限制、跨租户拒绝、现有产品展示/编辑及回滚；API Key 页面租户/用户两个 Tab，Robot Key 归入用户 Key。DB 迁移已经完成，不重复破坏旧数据。记录实际部署镜像 ID、接口响应和测试结果。

**阶段 B — Symbol 数据整合与 APS→MD 价格映射**

先阅读现有 AdminSvr Symbol 组装/推送以及 MD 接收/恢复实现，确认现有协议/字段/快照/增量语义，再以向后兼容的方式扩展，禁止另建配置入口。MD 内存索引按 `(location,data_source_id)` 找到关联的所有产品，按产品代码扇出；BN/CUSTOM 源相同路径，索引价格必须区分 tenant/source 与价格类型（index/mark），验证过期、重绑定、停用和断线重订阅。APS 价格入口权限与来源归属须检查，避免串租户、乱序和旧价覆盖；不要替换现有 MD 行情盘口恢复语义。

**阶段 C — 真正的租户产品交易**

核查既有全局 `dc_symbol` 与租户 `dc_tenant_symbol` 的责任边界，把必要交易规则/注册信息传至 Order/Trade/MD/Liq/Projection；验证下单、撤单、撮合、委托/成交查询、余额、持仓、保证金、标记价风险和强平。不得用“产品草稿已保存”代替真实可交易证据；与现有 Common HA 快照/日志/恢复机制保持一致，不在高频价格路径查询数据库。

**阶段 D — Broker API / Python SDK / API Docs**

使用租户 API Key 创建代客账户、入金、下单、查询、发布自定义指数价和标记价；Robot 按已有两把用户 API Key 工作，租户 API Key 与用户 API Key 分离。SDK 按正式接口实现并提供端到端 demo；文档展示对外交易和价格发布，不暴露租户管理内部接口，WebSocket 补实时用法。验证失败响应、权限隔离、幂等/重复发布处理。

**阶段 E — 灰度与回归**

在 Demo 先选测试租户：Binance BTCUSDT → BTCUSDT/BTC001USDT 多产品扇出；自定义 CUSTOM_BTC → BTC002USDT；断开/恢复来源、动态重绑及多租户交叉测试。跑完整交易、风险/强平、Projection 权威一致性以及 Trade/Order/MD 重启和 HA；确认旧 BTCUSDT 及 Robot 正常。全部成功后才允许启用新产品交易，并记录发布 SHA、镜像、数据、各项验收结果。

### 进度与报告口径

截至本段录入：此前真实 MySQL 迁移及数据库外键验证、本地 AdminSvr 74 项回归、Tenant Web 构建已完成；**管理页面 Demo 镜像替换、Symbol/MD 价格路由、自定义产品交易、Broker Python SDK 端到端验收均未确认完成**。每个阶段应分别记录【代码已提交】【编译通过】【Demo 已部署】【端到端通过】，不允许混为一谈。遇到工具阻断，保留实际错误与最小可继续的代码进度，不声称部署成功。


## 强制验收方式（用户 2026-10-19 确认）

- **所有 Web 开发均采用真实部署后 Playwright E2E 验收**：浏览器访问正在运行的 Demo（不是静态源码或 mock），以合法租户/交易员身份完成导航、表单 CRUD、绑定/解绑、错误反馈、页面刷新保持、跨租户权限拒绝及桌面/移动端关键流程；保留截图、浏览器控制台和网络响应证据。新镜像构建成功不等于部署验收通过。
- **所有 API 开发均采用 Python API/SDK 端到端验收**：使用真实租户 API Key，不借用 Robot 的两把交易员 Key；执行代客开户、入金、创建/绑定来源和产品（若为内部管理操作则由合法管理会话单独执行）、发布 INDEX/MARK 价格、下单/撤单/撮合、查询委托/成交/余额/持仓，并核对 Projection/Trade/Liq 结果。兼容用户 Trader Key，明确两个角色权限；测试错误权限、跨租户拒绝、序列/过期/重播、断线恢复。
- **完成标准**：每一项需分别提供构建 SHA、镜像 ID、部署容器 ID、Playwright 测试报告/截图或 Python 脚本及其执行日志、业务数据一致性结论；旧租户 Robot/行情回归不能省略。没有真实执行不得标记 PASS。Playwright 只覆盖 Web；Python API 只覆盖 API；均需对真实 Demo 验证。

## 2026-10-19 Mac Demo 最新执行记录（逐项区分）

### 本轮已完成并有执行证据

- `bliplink/com.app.dc.adminsvr` / `saas-crypto`：新增 `TenantRoutedSymbol`，在 `TenantSymbolService.effectiveSymbols()` 中按同租户 `location,data_source_id` LEFT JOIN `dc_tenant_data_source`，把 `location/product_name/data_source_id/source_type/source_symbol/data_source_enabled` 随**现有 querySymbol 返回的 Symbol** 一起序列化；未创建新的 MD 配置加载路径。提交：`379c178`（DTO）、`bff87c2`（SQL/映射）、`f97d2ed`（契约测试）。此阶段**只处理已有全局产品的租户来源元数据**，不会将自定义草稿投入交易。
- Mac mini Java 8 Maven 离线测试：**76 tests, 0 failures, 0 errors, 1 skipped**；新增的 DTO 运行时 JSON 兼容及 JDBC public 继承字段检查均通过。
- 已本地构建并重启 Demo AdminSvr 镜像：`local/dc-saas-adminsvr:tenant-symbol-source-20261019`，镜像 `sha256:0609da853eaaafdb66d657b42157f9739e1b26bf811e3b0eef19ddfc67d07e90`。Tenant Web 镜像仍为 `local/dc-saas-tenant-web:product-source-20261019`，镜像 `sha256:167906628eb859bd6dc6d370e7ac6d5dd90438a790eee9bb13bfb7b5892d3d6a`。
- Mac Demo MySQL 只读查询证实 `dc.dc_tenant_symbol` 和 `dc.dc_tenant_data_source` 存在；带双 location/data_source_id 条件的联表在 GW7XMI 返回 BTCUSDT 的旧兼容记录，`data_source_id=NULL`（LEGACY），未对现有产品绑定或资金做写入。
- **真实部署后的 Playwright Chrome**：`http://127.0.0.1:18092/?location=GW7XMI` 在 1365×900 和 390×844 均 HTTP 200，能找到登录按钮与租户 ID，无横向溢出和 JS pageerror。
- Docs 正在运行的镜像内已存在 `opentradingcore-0.1.0-py3-none-any.whl` 和对应 SDK 源码 zip；**仅确认产物存在，未证明 Python SDK 真实交易 E2E**。

### 尚未通过 / 不得误报

- 使用无会话 Python HTTP 请求 `AdminSvr/querySymbol` 返回 `code=9000, msg=INTERNAL_ERROR`；既不能据此证明携带有效授权会话的 Symbol 业务成功，也不能判断是 SQL 失败。需在已认证的合法测试会话下复验并核查调用入口。
- Playwright 自动创建测试租户/登录的执行被运行环境安全检查拦截；**新租户未创建，登录后 CRUD 未完成**，不借用 Robot Trader Key 充当 Tenant API Key。
- 使用部署版 SDK Wheel 的 Python 测试命令被运行环境安全检查拦截；真实 Broker API Key 的开户/入金/交易/发布价格全流程仍无 PASS 证据。
- MdSvr 源码当前仍未消费来源关联信息；原 `IndexInput.indexList` 用于系统指标订阅，不能将它误认作已完成的租户产品数据源绑定；MD 的 Broker price publish 仍由现有功能开关控制。独立自定义产品还受 `TenantSymbolService.effectiveSymbols()` 的 `JOIN dc_symbol` 约束，Order/Trade/Liq/Projection 的租户独立产品交易规则/风控仍待开发验收。
- **绝不可启用新产品交易或宣告整体完成**。下一步应先完成实际 AdminSvr→MD Symbol 消费路径、独立产品规则扩展，再通过部署后 Playwright/合法租户 Python SDK 跑 end-to-end 与风控对账。
