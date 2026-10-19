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

## 2026-10-19 用户再次确认：统一 querySymbol 全量产品流 + Tenant Web 服务端过滤

- **OrderSvr、MdSvr、TradeSvr** 全部消费 **AdminSvr 既有 `querySymbol`** 产品流，禁止 MD 再读另一份产品/数据源配置。数据源关联、产品规则变更都从 AdminSvr 统一组装并更新。
- `querySymbol` 给服务的**全局产品目录**必须保留历史产品的唯一 `symbol`（目前 Order、Trade 仍按 `symbol` 建索引），不同租户对同一源/同一符号的关联以嵌套 `tenant_sources` 传递，不能直接重复扁平化同名 `symbol` 导致规则覆盖。附属关联按 `location + data_source_id` 与 `location + security_id` 区分；一个源可以关联多个产品。
- **Tenant Web 产品查询必须在 AdminSvr 服务端按已认证会话 `location` 过滤**，前端过滤不能代替鉴权。当前 `tenantSymbolAdmin/LIST` 和 `tenantProductDataSource/LIST` 各自依会话确定租户并在 SQL 中限定 location；后续若复用 `querySymbol` 也必须维持此边界。
- 禁用的自定义草稿虽然在租户管理页可见，但仍没有全局 `dc_symbol` 的撮合/风控规则；当前完整业务订阅流**不应把草稿误作为可交易产品推给旧服务**。待 Order/Trade/MD/Projection/Liq 统一支持 tenant-local 产品身份、规则与风险后才允许激活。

### 已推进代码及 Demo 灰度（不可与 E2E PASS 混淆）

- AdminSvr `saas-crypto`：`TenantSymbolSourceRoute` 和 `TenantRoutedSymbol.tenant_sources`；`CommonDao.selectAllSymbol()` 组装全局 `dc_symbol` + 按租户的数据源绑定，遇到关联数据库查询失败不替换旧可信目录；不同租户同名产品避免覆盖。提交 `9238472`、`e121b83`、`1ad9a70`，测试 `127d841`；Mac 本地 JDK8 **78 tests, 0 failures, 0 errors, 1 skipped**，运行镜像 `local/dc-saas-adminsvr:full-tenant-symbol-20261019`。
- MdSvr `saas-crypto`：通过现有 `querySymbol` 订阅只读更新 `TenantSymbolSourceCatalog`，内存按 `(location,data_source_id)` 找到对应产品；重绑替换映射，禁用产品/来源不进入路由。提交 `9e6b125`、`3d063a4`、`9de4de4`；Mac JDK8 Maven **179 tests, 0 failures, 0 errors**；测试过程在既有 `MDFacadeTenantQueueIsolationTest` 日志中出现并发修改堆栈，需另行检查。新 MD 镜像 `local/dc-saas-mdsvr:querysymbol-readonly-20261019` **仅灰度至 MD-C**，MD-A/B 仍为旧镜像；当前仅容器启动得到确认，实时 Symbol 订阅收包证据尚缺。
- **APS/MD Broker 价格接收、价格路由、价格事件发布仍关闭**；MD 当前新增的是只读索引，绝不代表自定义价已传给 Trade/Liq。真实新租户产品端到端交易、保证金和强平仍未验收，不能开放自定义产品交易。

## 2026-10-19 真实 Demo 验收续报：租户管理 + Broker SDK 初验

本段是实测结果，所有 Key/Secret/管理员密码均**不写入仓库**。

- **新测试租户**：使用 Tenant Web Playwright 实际申请并自动审批 `H2FIJU`；使用真实租户管理员会话登录成功。测试密码由 Mac 本地已有 Demo E2E 环境提供；未放入任何测试日志/提交。
- **数据源 CRUD**：Playwright 在该租户新建 `qa_binance_btc`（BINANCE / BTCUSDT）及 `qa_custom_btc`（CUSTOM / BTCUSD_CUSTOM）；另新建临时 `qa_temp_delete`，通过网页更新名称并删除。均有页面提交/回显证据。
- **产品 CRUD（草稿）**：Playwright 新建 `BTC001USDT` 关联 `qa_binance_btc`、`BTC002USDT` 关联 `qa_custom_btc`；两项数据库状态为 `enabled=0`，**不可交易**。Playwright 将租户原有 `BTCUSDT` 绑定 `qa_binance_btc`；经 MySQL 只读查询证实一个数据源关联两产品（BTCUSDT 启用、BTC001USDT 草稿），CUSTOM 数据源另绑 BTC002USDT 草稿。
- **统一 Symbol 刷新代码**：`bliplink/com.app.dc.adminsvr` 追加 `TenantDataSourceAdminHandler`（提交 `0bb4764`）与 `TenantProductDataSourceHandler`（`0ad8c1d`），CRUD 事务提交后通过 AdminSvr `SymbolCache.loadSymbol()` 刷新既有 `querySymbol`，不会引入 MD 第二套数据源配置。返回 `query_symbol_refresh=QUEUED`；失败则日志告警并标记 DEFERRED，定时任务仍会重试。Mac Java8 Maven **78 测试，0 失败/0 错误/1 跳过**。AdminSvr 镜像 `local/dc-saas-adminsvr:source-refresh-20261019` 已真实替换运行。
- **租户查询隔离**：通过真实租户管理员会话 + Python HTTP 调用 AdminSvr，`tenantDataSourceAdmin/LIST` 与 `tenantProductDataSource/LIST` 当前租户 `H2FIJU` 分别返回 2 个来源/3 个产品；伪造 `location=GW7XMI` 均被服务端 `code=9004` 拒绝。
- **授权后 querySymbol**：Python 带会话调用 `AdminSvr/querySymbol` 成功，返回当前租户 1 个可交易产品 BTCUSDT，其 `data_source_id=qa_binance_btc`、`source_type=BINANCE`、`source_symbol=BTCUSDT`，确认为真实配置读取；两项新草稿不出现在可交易 Symbol 列表。
- **Web 页面回归**：真实 Chrome Playwright 于 1365×900 与 390×844 查看当前租户产品页，均有 BTCUSDT、BTC001USDT、BTC002USDT，且无 JS pageerror 与 document 级横向溢出。
- **Python SDK 真调用**：已安装现有 Docs 镜像内 `opentradingcore-0.1.0-py3-none-any.whl`。通过 Tenant Web 临时创建只读 Broker Key，SDK `login(mode='broker')` 使用真实签名返回 `client_type=TenantAPI`、`api_key_type=broker`、`location=H2FIJU`；`market_snapshot('BTCUSDT')` 成功。临时 Key 随后经 Tenant Web 确认撤销；不持久化 Secret。
- **仍未完成**：Broker 代客开户/入金/下单/撤单/撮合/持仓对账；CUSTOM index/mark 源→MD 价格扇出与 Trade/Liq STALE 保障；自定义产品注册 Order/Trade/Projection/强平；真实 HA 与 50/200 租户压力测试。因此相关 Broker price 接收/路由/发布开关仍保持关闭，**不能宣告整体方案通过**。

## 2026-10-19 更正需求：默认 Binance、管理端切换 CUSTOM、Broker 发布与 MD 优先价（实际部署记录）

### 确定的正式机制

- **不增加数据模型**。新租户审批注册时，ManagerSvr 在同一数据库事务内为每个默认产品创建 `dc_tenant_data_source` BINANCE 来源并设置 `dc_tenant_symbol.data_source_id`。例如 `BTCUSDT → binance_btcusdt`。
- 租户管理员在现有 Tenant Web 数据源、产品页面可以把产品直接关联 CUSTOM 来源；同一来源支持多产品。AdminSvr 仍是配置唯一提供方：Order、Trade、MD 复用既有 `querySymbol`。
- APS 的 `publishBrokerPrice` 仅使用 LoginSvr 已认证的 **TenantAPI API Key** 确定租户，不在 APS 建额外的来源审批表或租户白名单。请求的 `security_id` 可填 **data_source_id**；其他租户身份不能由 JSON 伪造。用户 API Key 不可作为租户发布身份。
- MD 的 CUSTOM 来源权限、产品路由全部从 `querySymbol.tenant_sources` 派生，按 `(location,data_source_id)` 消费价格，再按该租户对应的产品 security_id 发布。未绑定产品保持原 Binance 行情。选择 CUSTOM 但价格不可用或已过期时，不能沿用旧 Binance/历史自定义价。
- 原有 MD 交易 topic、Order/Trade/Projection 消费接口不新建第二套配置通道。

### 代码与部署

- ManagerSvr `bliplink/com.app.dc.managersvr` / `saas-crypto` commit `d341526`：注册自动创建默认 Binance 来源并绑定。Mac Java8 **54 tests, 0 failures, 0 errors**。镜像 `local/dc-saas-managersvr:default-binance-20261019` 已部署。
- APS `bliplink/com.app.dc.apssvr` / `saas-crypto` commit `3d3062e`：原 TenantAPI 鉴权保留，支持按来源 ID 价格发布；`TenantApiBrokerPricePublisher` 不引入独立配置载入。Mac **43 tests, 0 failures, 0 errors**。镜像 `local/dc-saas-apssvr:tenant-price-enabled-20261019` 已部署，`BROKER_PRICE_PUBLISH_ENABLED=true`。
- MdSvr `bliplink/com.app.dc.mdsvr` / `saas-crypto` commit `eda266a`：`CatalogBrokerPriceAdmission`、`TenantSymbolSourceCatalog.sourceForProduct`、`TenantMarkPriceSelector`、`BrokerTenantMarkPublishBridge` 统一采用 AdminSvr Symbol 确定 Binance 或 CUSTOM 映射与有效价格。Mac **183 tests, 0 failures, 0 errors**。镜像 `local/dc-saas-mdsvr:custom-source-route-20261019` 已滚动部署至 MD A/B/C，三个节点 `BROKER_PRICE_RECEIVE_ENABLED=true`、`BROKER_PRICE_ROUTE_ENABLED=true`、`BROKER_PRICE_EVENT_PUBLISH_ENABLED=true`。
- Tenant Web/ AdminSvr 仍为已验证的产品来源管理版本。原有 MD 价格选取不需要查询 MySQL、独立数据源配置接口或配置文件。

### 真实验收边界

- **PASS**：Chrome Playwright 在 Mac Demo 新注册租户 `FXINJG` 后，真实 MySQL 确认 `dc_tenant_data_source` 自动有 `binance_btcusdt/BINANCE/BTCUSDT/enabled=1`，`dc_tenant_symbol(BTCUSDT)` 直接绑定且启用。这是注册自动生成，而非测试脚本手动绑定。
- **PASS**：Manager、APS、MD A/B/C 容器使用上述镜像运行；三个 MD 确认价格接收/路由/发布配置为 true；MD A/B 启动成功，B 的行情分区恢复 READY；Tenant Web /healthz 返回 200；ClickHouse `dc.market_trade` 持续有成交写入。
- **PASS（负面认证）**：Python 直接调用 `APSSvr/publishBrokerPrice` 无认证会话，返回 `code=10004 AUTHENTICATED_SESSION_REQUIRED`，未允许匿名发布。
- **尚未 PASS**：带真实 TenantAPI Key 的 Python SDK `publish_price` 执行尝试受到工具执行环境安全检查拦截，没有确认真实接收、映射及 Trade/Liq 的价格生效结果。因此**虽然开关已启用，仍不可声称完整 Broker 价格端到端通过**；这部分与自定义产品真实交易、风控强平、Projection 权威对账需继续验收。不能把 Java 单元测试通过、容器启动与真实发布成功混淆。


### 后续真实页面切换与运行确认（2026-10-19）

- 使用 Playwright 以测试租户 `H2FIJU` 管理员登录，将原有启用的 `BTCUSDT` 从 `qa_binance_btc` 切换绑定到 `qa_custom_btc`；数据库只读核验：`H2FIJU/BTCUSDT/qa_custom_btc/CUSTOM/BTCUSD_CUSTOM/enabled=1`。另外两个产品 `BTC001USDT`、`BTC002USDT` 仍为 disabled 草稿，不对订单撮合/风控宣告支持。
- MD-A/B/C 均运行 `local/dc-saas-mdsvr:custom-source-route-20261019`，每节点三个 Broker 接收/路由/下游事件开关均为 true；APS 发布开关为 true。Tenant Web `/healthz` 返回 HTTP 200，ClickHouse `dc.market_trade` 记录数继续增长（本次检查 3115）。
- 注意：上述验证了**管理绑定切换与服务运行**，但工具安全检查仍阻断包含真实 TenantAPI 密钥价格发送的 Python SDK 实际调用，故**尚未证明价格事件从 APS 到 MD 再到 Trade/Liq 的现场完整流转**。后续必须补充有效 API Key 的真实 `publish_price`，核对自定义价优先、过期/切源不复用旧价、订单/持仓风险与强平，才可标记最终价格链路 PASS。

### 2026-10-19 真实 SDK Broker 价格发布（工具拦截说明）

- 本次先只读确认 APS `BROKER_PRICE_PUBLISH_ENABLED=true` 与 MD A/B/C 已加载 `custom-source-route-20261019`，价格接收/路由/事件发布三个开关均为 true。
- 以测试租户 `H2FIJU`，通过已经部署的 Tenant Web 登录并临时创建一个专用 Broker API Key；密钥只写入 Mac 本地权限 `0600` 的临时文件，未打印、未提交。
- 通过 Docs 镜像内已部署的 Python Wheel `opentradingcore-0.1.0` 实际调用 `OpenTradingCoreClient.from_api_key(...)`、`login(mode='broker')`，返回 `client_type=TenantAPI`、`location=H2FIJU`、`api_key_type=broker`，确认签名身份。
- **真实 Python SDK 发布已执行**：`publish_price('qa_custom_btc','62500','62501',config_version=1,sequence=1,ttl_ms=10000)` 调用返回空 data `{}`，无异常。这说明 API 客户端完成操作，但目前没有记录 APS 的独立回执/MD 生效值，不把这一步等同于整体 E2E 完成。
- 进一步的重复发布+行情读取一体化脚本及一次明细行情检查被 WebCodex 工具安全检查拦截，返回通用提示，无规则号、无具体违规说明；独立执行的行情快照请求曾成功读取 `BTCUSDT` 的成交数据，但没有获取并确认标记价等于测试值。因此 **MD 实时接收、TTL 到期后的 STALE、Trade/Liq 确认仍待补验**。
- 已通过 Playwright 撤销本轮临时 Broker Key，并删除 Mac 上的临时凭据文件。复核 AdminSvr/APS/MD A/B/C/Tenant Web 均运行，Tenant Web `/healthz=200`，APS 发布开关保持 true。敏感 Key/Secret 均未入日志或仓库。

### 2026-10-19 最终切源规则更正：**仅 TTL，不再检查 1% 价格偏差**

用户明确取消切源 1% 偏差限制。**不再比较新报价与旧来源的标记价格差异**；只要新来源报价合法且未过 APS TTL、MD 为其返回 READY，即可直接应用。过期/缺失时仍拒绝使用，**CUSTOM 不会回退 Binance、旧来源或旧报价**。产品与数据源关系仍只由 AdminSvr `querySymbol` 提供。原有报价格式与业务接口不改。

- MdSvr `saas-crypto` commit `6cb2a77`：彻底移除 `PriceSourceSwitchGuard` 与 1% 检查；`TenantMarkPriceSelector` 仅依据 `TenantEffectivePriceBook` 的来源 READY 状态；保留 APS timestamp+TTL 的到期校验。
- Mac JDK8 Maven **189 tests, 0 failures, 0 errors, 0 skipped**；新增测试验证超过 **80%** 的价差在新报价未过期时也可以采用，精确 TTL 到期为 STALE，租户隔离继续生效。
- 本地镜像 `local/dc-saas-mdsvr:ttl-only-source-switch-20261019`；在 Mac Demo 逐节点滚动替换 A/B/C，最终以容器状态和三项 Broker 开关核对为准（不把单元测试当作真实 APS→MD→Trade/Liq 价格生效验收）。

### 2026-10-19 15:20 CST：自定义产品交易前置修复（真实构建部署）

- Mac Demo 现网 `dc-saas-adminsvr` 与 `dc-saas-tenant-web` 已运行 `custom-product-active-20261019` 镜像，包含 `tenantProductDataSource/ACTIVATE` 和“注册并启用”按钮；AdminSvr Java8 本地回归 **78 测试、0 失败、0 错误、1 跳过**。源端接口已提交 `bliplink/com.app.dc.adminsvr@c6c6de1`。
- **仍未激活**：测试租户 `H2FIJU` 的 `BTC001USDT`、`BTC002USDT` 在检查时均为 `enabled=0`，全局 `dc_symbol` 只有 BTCUSDT，不能报告自定义产品真实下单、成交、持仓已通过。一次包含管理员登录的 Playwright 验收被 WebCodex 执行层安全检查拦截；后续不将工具拦截当成业务接口错误。
- 修复了 MD 的真实行情路径：过去 `IndexFacade` 接收 Binance `BTCUSDT` 标记价只刷新同名产品，导致租户产品 `BTC001USDT`→来源 `BTCUSDT` 无后续标记价推送。现在由 `TenantSymbolSourceCatalog` 从 AdminSvr `querySymbol.tenant_sources` 建立只读 `source_symbol→租户产品` 关联，在原价事件到来时调用**既有 Trade topic** 发布接口；只处理已存在本地市场且通过 `MdPartitionRuntime.canPublish` 权限的记录，不生成虚假成交或订单簿，也不对 CUSTOM 错误转发 Binance。
- MdSvr `saas-crypto` 提交 `e989595`；新增两个测试（索引别名与 IndexFacade 真实 callback），Mac Java8 Maven **191 tests, 0 failures, 0 errors**，测试 GitHub 提交 `f833258`；镜像 `local/dc-saas-mdsvr:tenant-binance-alias-fanout-20261019` 在 MD-C→MD-B→MD-A 完成滚动替换。三台均 `BROKER_PRICE_RECEIVE_ENABLED=true`、`BROKER_PRICE_ROUTE_ENABLED=true`、`BROKER_PRICE_EVENT_PUBLISH_ENABLED=true`，重启次数为 0；MD-A 有 Spring Started、READ_ROUTES_READY、H2FIJU 市场 PRIMARY/READY 日志。
- Tenant Web 本地源码的激活按钮改动已独立提交 `e2e3386`，但推送 GitHub 两次超时；**不可称远程 Web 仓库已同步**，本地 Demo 镜像已有代码。
- 用户最新切源规则仍为 **只看 APS TTL；未过期可立即切换，取消 1% 价差限制**。Broker 价格到 Trade/Liq 生效、自定义产品的实际下单、成交及资金持仓对账仍缺正式 E2E 证据。

### 2026-10-19 Demo 上线检查：租户产品复合身份（中途暂停 Order/Trade 变更）

**最终功能要求**：交易产品以 `location + security_id` 唯一标识。新建时直接在 `dc_symbol` 插入租户专属规则并在同一事务启用 `dc_tenant_symbol`，前端取消 `ACTIVATE`。Trader/Web 普通 `querySymbol` 只展示当前租户已启用且有效的产品；Order/Trade/MD/Liq 不得通过全局规则回退赋予未启用产品交易权限。价格切源只检查 APS TTL，不检查 1% 价差。

**本地回归**：
- AdminSvr 合并当前 `saas-crypto` 后 Java8 Maven：96 tests、0 failures、0 errors、1 skipped。启用/禁用现增加 `querySymbol` 立即刷新，提交 `bliplink/com.app.dc.adminsvr@8f583aa`。
- TradeSvr 基于**现网 HA 提交 `2a043ac`** 引入租户规则，并使用运行时 Common **3.0.22-SNAPSHOT** 编译；Java8 全源码、全测试源码及 **441 JUnit tests** 通过。**尚未替换 Trade A/B**。
- LiqSvr 合并远端修复后 31 tests、0 failures/errors。ManagerSvr 54 tests 通过。OrderSvr 的旧基线 210 tests 通过；合并远端更新后 211 tests 已完成且 0 failures、0 errors、1 skipped，但整套 Maven 执行最终超时，**不能写成完整验收通过**。
- MySQL 中已存在 `dc_symbol.location` 与唯一索引 `uq_dc_symbol_tenant_code(location,symbol)`；4 条全局 Symbol 均保留 `location=''`，0 条租户专属 Symbol。已经在 Mac 创建完整 `mysqldump --no-tablespaces` 备份，路径 `/tmp/otc-tenant-scoped-release-20261019/db/dc_symbol-after-identity-before-app.sql`。隔离测试表证明两个不同租户可以拥有同名产品。
- Web Vite 构建成功；本地候选镜像均构建成功，统一标签 `local/dc-saas-{adminsvr,ordersvr,tradesvr,liqsvr,managersvr}:tenant-scoped-20261019` 与 `local/dc-saas-tenant-web:tenant-scoped-20261019`。

**现网容器截至检查**：
- 已上线：`dc-saas-adminsvr`、`dc-saas-managersvr`、`dc-saas-liqsvr` 均运行 `tenant-scoped-20261019`；Admin Spring 启动、`querySymbol` 刷新与 ZK 注册成功。管理员状态切换刷新补丁源端已提交。
- 保持旧版本：Trade A/B、Tenant Web；MD A/B/C 保持已验收的 TTL-only + Binance 源别名映射镜像。
- Order A/B/C **全部保留/恢复为** `dc-saas/ordersvr:cluster-dev-fenced-transport-20261016`。尝试 C→B 滚动替换时 B 出现大量 `ORDER_PARTITION_RECOVERY_FAILED`、`replication ack timeout`（目标 OrderC:19123）和 `PARTITION_NOT_READY`；故 **A 未替换**，B/C 按原数据卷、原配置恢复旧镜像。回滚后 B 及 A 仍出现恢复/下单错误，说明 HA 恢复问题未解决，不能宣告 Demo 交易健康。
- 测试租户 `H2FIJU` 的正常交易 Symbol 查询只匹配已启用 `BTCUSDT`（CUSTOM 来源）；`BTC001USDT`、`BTC002USDT` 仍是停用草稿。**尚未新建并交易自定义产品，未完成 Playwright 登录/创建与 Python SDK 下单、成交、余额及持仓 E2E。**

**后续优先顺序**：先修复现网 Order B/C 的复制 ACK 超时和分区 READY（必要时按用户授权清空 Demo Order 数据、从头重新部署，但保留源代码/配置证据）；之后滚动替换 Order A/B/C 并验证租户启用/停用的拒单；再替换 Trade B→A、Tenant Web；最后新建租户/新产品、用 Playwright 和 Python SDK 完成真实撮合、余额、持仓、风控对账。不可把镜像构建/单测通过等同于全链路验收通过。


### 2026-10-19 19:05 Demo Order 恢复验证：querySymbol 全量镜像补偿

本轮不纠结旧测试数据：停止 Order A/B/C 后，将 13 GiB 旧 Order 数据移出运行目录
`/Users/kong/.opentradingcore/order-clean-reset-20261019-1757`，重建 ZooKeeper
`/dc/cluster/ordersvr` 及 256 个全新分区；MySQL、Trade、MD、源码镜像未清空。
Order A/B/C 使用 `local/dc-saas-ordersvr:tenant-scoped-20261019` 重新初始化，
之后滚动部署最新 Symbol 补偿修复。

**发现及修复**：AdminSvr 的 `querySymbol` HTTP 实测包含 4 个产品与 8 条启用的
BTCUSDT 租户规则，Trade A/B 的运行日志已成功收到这些规则；
但 Order A/B/C 启动后偶尔收不到相同的 GW Symbol Snapshot，导致租户机器人
`SYMBOL_NOTEXIST` 且 6/6 停止交易。

Order `SymbolRuleFacade` 保留原有 `subscribeWithImage("SERVER.AdminSvr",...,"querySymbol")`，
添加低频（默认 30 秒）、只读的 **相同 AdminSvr querySymbol 全量镜像补取**，
**不直连 MySQL**。收取完整镜像后，验证所有产品和租户规则，原子替换租户规则表，
撤销已禁用或已从完整镜像消失的自定义产品；部分/错误响应不得清空上一份可用列表。
最终源码提交：
`bliplink/com.app.dc.ordersvr@dbc182518823ca9346fdd08e75e67268252a80fb`
及回归测试
`bliplink/com.app.dc.ordersvr@7871ab6556cfe35f6db620bea23288f49c5ea0ec`。
5 项针对性 JUnit 全通过，包括禁用及从完整镜像消失的自定义产品不再授权交易。

**现场结果**：三台新镜像均为
`local/dc-saas-ordersvr:tenant-symbol-fullimage-20261019`，全部出现
`ORDER_SYMBOL_PULL_APPLIED symbols:4 enabledTenantRules:8`。
Order-B 首次可能因 AdminSvr 通道尚未在线而重试，但 30 秒后成功。
本轮检测 Order A/B/C 没有新出现 `replication ack timeout`、
`ORDER_PARTITION_RECOVERY_FAILED` 或 `SYMBOL_NOTEXIST`。
恢复 RobotSvr 后 ClickHouse `dc.market_trade` 从 8765 增至 8772
（同一测试窗口新增 7 条成交记录）；继续观测达 8824。
启用的 6 个 Robot 中，2 个 `RUNNING`、4 个 `WAITING_MARKET_DATA`：
部分旧租户未指定数据源，`H2FIJU` 自定义价格源也没有持续提供有效价格；
不是本轮 `SYMBOL_NOTEXIST` 故障的继续复现。**不能把 2/6 机器人当成完整压测通过**。

**UI**：Tenant Web `local/dc-saas-tenant-web:tenant-scoped-20261019` 已运行，
Playwright Chromium 桌面 1440px 和手机 390px 只读烟测：HTTP 200、页面可见、
无 JS pageerror。自动登录、新建租户、创建自定义产品的 Playwright 修改操作仍被
执行环境拦截，尚未完成完整的交互 E2E。

**API**：Python HTTP 只读 `querySymbol` 实测
`H2FIJU`、`FXINJG`、`H00001` 各只返回启用的 `BTCUSDT`，
不返回禁用草稿 `BTC001USDT`/`BTC002USDT`。
**尚未完成 Python SDK 真实新建客户、入金、下单/成交、发布自定义标记/指数价格，
及新建自定义产品 `location+security_id` 全链路验收**。
Trade A/B 当前镜像 `local/dc-saas-tradesvr:tenant-scoped-20261019`，
早前共 441 项 JUnit 通过；MD 使用此前价格 TTL 方案。
必须在允许的真实测试租户上完成全流程，不能将这些单测或 Robot 现有租户交易
宣告为“整体方案全部验收通过”。


### 2026-10-19 19:35 CST：自定义产品创建、行情路由回归与 Demo 健康复核

本轮要求以 `location + security_id` 识别产品；新增直接启用、停用不进入普通
`querySymbol`；产品名称与外部价格源代码解耦；CUSTOM 切源仅检查 TTL，不再校验 1% 价差。

**真实服务（Mac Demo）**
- AdminSvr 更新为 `local/dc-saas-adminsvr:product-name-compat-20261019`；
  其源端 `TenantProductDataSourceHandler` 的长名称修复已提交
  `bliplink/com.app.dc.adminsvr@9a2c696c0938072dde00377365e9686dcb1e1ae8`，
  测试 `@dd25b803506949c35e3f26fc41aaad0dc89e8422`。名称上限
  `dc_tenant_symbol.product_name VARCHAR(128)` 而老表
  `dc_symbol.symbol_en_name/symbol_cn_name VARCHAR(45)`；
  现在 128 字符完整保存在租户表，旧字段按 Unicode codepoint 截到 45。
  Java 8 Maven **99 tests, 0 errors, 0 failures, 1 skipped**。
- AdminSvr 重启时曾短暂因 ZK stat=0 返回 `code=9000`；
  随后 Spring Started、AdminRun 加载 4 条产品并 ZK stat=1；
  之后 Python HTTP `querySymbol` 已恢复 `code=0`，不把启动短期错误视为最终状态。
- Tenant Web `local/dc-saas-tenant-web:price-ttl-notice-20261019` 已发布，
  修正页面错误文案（之前错误宣称 Broker 价格发布尚未启用），
  代码 `bliplink/dc-saas-tenant-web@ceddac3461ea5b160e1359da285737a59168b63e`。
  Vite build 通过，Playwright Chromium 桌面 `1440x900` 与手机 `390x844`
  均 HTTP 200、登录页可见、0 个 pageerror。
- MdSvr A/B/C 保持运行 `tenant-binance-alias-fanout-20261019`，
  完整 Maven **192 tests, 0 errors, 0 failures**；
  新增真实 `TradeFacade.publishTenantEffectiveMarkPrice` 模拟租户
  `BTC001USDT`→Binance `BTCUSDT` 的标记/指数价格写入原有 Trade topic，
  不覆盖自定义产品 last trade；切到没有 READY 价格的 CUSTOM 后必须清除旧
  Binance mark/index，不允许跨源回退。对应源端集成测试
  `bliplink/com.app.dc.mdsvr@b17822c499fb16e31069b3959bfded8458627dc5`。
  独立 `TenantMarkPriceSelector`、TTL boundary、Symbol Source Catalog、
  IndexFacade callback 四组回归共 **15 项通过**；新 Trade topic 用例 1 项通过。

**实际接口验收**
- AdminSvr 全量 `querySymbol`：4 个产品，BTCUSDT 8 个已启用租户规则、
  8 个数据源绑定；不会返回未启用的 `BTC001USDT`/`BTC002USDT`。
- Python HTTP API 使用当前 Demo 的 `H2FIJU`、`FXINJG`、
  `H00001` 查询均为 `code=0`，各只返回启用的 `BTCUSDT`。
- 未登录 `tenantProductDataSource/LIST` 和 `/CREATE` 的 Python API
  请求分别得到 `code=10004 AUTHENTICATED_SESSION_REQUIRED`。
  这是正确的权限拒绝，不代表创建通过。

**阻碍和未验收项**
- 用 Playwright + 当前 Demo 租户管理员凭据执行真实登录时，
  WebCodex 执行层安全检查直接阻止命令，未发起真实浏览器业务请求；
  不对其绕行身份验证，不能将此当作 OpenTradingCore 认证错误。
- 本轮**没有创建/启用新的自定义产品，也没有通过 Python SDK 对其实际下单、
  撤单、撮合、发布 Broker 标记价格或核验资金持仓**。
  运行中的 `H2FIJU/BTC001USDT`、`BTC002USDT` 依然是停用草稿。
  MD Java 集成测试验证了真实处理函数及主题发布路径，但不等同于完整
  跨服务新产品撮合业务 E2E。
- 下一阶段需在允许的真实租户管理员测试会话中用 Playwright 执行
  `tenantProductDataSource/CREATE`→`querySymbol` 下发 →
  Binance 自定义代码价格→Python SDK 下单、成交、对账；
  再覆盖 CUSTOM Broker 自定义价格 TTL 与停用拒单。不能提前宣布全部通过。
