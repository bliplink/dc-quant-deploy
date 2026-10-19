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
