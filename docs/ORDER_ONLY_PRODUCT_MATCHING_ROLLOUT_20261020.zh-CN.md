# 产品级 Trade / Order-only 撮合模式：Demo 镜像部署与验收

日期：2026-10-20。本文只涵盖租户自定义产品撮合模式，不代表独立的 Common/Trade HA 验收已完成。

## 一、业务定义

- **按产品配置，而不是按租户配置**：产品的业务主键 `location + security_id`；一个租户同时可有 `TRADE` 与 `ORDER_ONLY` 两种产品。
- 新增产品选择 `matching_mode`：`TRADE`（默认）或 `ORDER_ONLY`。
- `TRADE`：原 OrderSvr 撮合和 TradeSvr 资金冻结、余额、持仓、风控路径；旧产品兼容默认值。
- `ORDER_ONLY`：OrderSvr 纯订单处理、撮合、委托/成交回报及 MD 行情，不调用 TradeSvr 来更新该产品的客户资金和持仓；不产生 TradeSvr 风控/平仓/强平担保。
- **模式创建后不可编辑**。对单产品进行资金账本与结算规则切换需要独立的完整迁移流程；本轮禁止修改现有产品模式。产品停用后仍保留原模式，供历史订单撤单/恢复。
- 禁用产品仍按原业务门槛，不允许新增交易；不要通过更改 `trade_enabled` 模拟 ORDER_ONLY 模式。

## 二、代码、数据库和配置

1. 数据库：`mysql/migrations/20261020_tenant_product_matching_mode.sql` 为 `dc_tenant_symbol` 增加 `matching_mode ENUM('TRADE','ORDER_ONLY') NOT NULL DEFAULT 'TRADE'`，幂等执行。Demo 中已应用两次并验证兼容；当前全部 **38** 个历史产品均为 `TRADE`。
2. AdminSvr：`TenantProductDataSourceHandler.CREATE` 校验模式并入库；`LIST` 返回模式；`BIND` 只能替换唯一当前价格源，不能改撮合模式；`CommonDao.selectAllSymbol` 的内部 `querySymbol` 完整画像携带每个租户/产品的 `tenant_matching_modes`，包含已停用产品的模式，防止历史订单路由被更改。公开匿名 `querySymbol(location)` 仍仅返回该租户启用产品，不能访问管理接口。
3. OrderSvr：`SymbolRuleFacade` 解析完整的租户产品模式快照，默认旧产品是 `TRADE`，未知模式或找不到模式时拒绝，而不是默默降级到默认资金链。新增 `ProductMatchingExecOrder` 作为主执行器，将 New / Cancel / Trade 路由给现有 `TradeExecOrder` 或 `DefaultExecOrder`，同批跨模式执行拒绝。
4. 租户前端：`Symbols.jsx` 新增产品时可选 **Trade · 资金风控**（默认）或 **Order-only · 纯撮合**；已创建产品列表显示对应模式，明确创建后不可修改。
5. 本轮只替换业务类，并以原 Demo 镜像为父镜像，保留 Common `AsyncSingleSeqThreadGroup` 同 Key 队列修复和所有现有持久化/恢复类，避免与另一 Codex HA 开发交叉。

GitHub 提交/交付分支：

- Admin：`bliplink/com.app.dc.adminsvr` 的 `codex/tenant-product-matching-mode-20261020`，`1354c0b`（之前 `0e170d8` 统一 Robot 与普通用户数字 user_id 并修复公开 24h 统计）。
- Order：`bliplink/com.app.dc.ordersvr` 的 `codex/order-product-matching-mode-20261020`，`3f38bf9`。
- Tenant Web：`bliplink/dc-saas-tenant-web` 的 `codex/tenant-product-matching-ui-20261020`，`d1d0a39`。
- 部署仓库：`bliplink/dc-quant-deploy`；Compose 覆写在本仓库 `config/`，迁移在 `mysql/migrations/`。

## 三、已经实际部署到 Mac Docker Demo 的镜像

| 服务 | Demo 镜像 / 状态 |
| --- | --- |
| AdminSvr | `local/dc-saas-adminsvr:product-matching-mode-20261020`：运行；叠加此前数字交易员 ID 和 24h 统计修复 |
| Order A/B/C | **三台同镜像** `local/dc-saas-ordersvr:product-matching-mode-20261020`；按 C → B → A 滚动替换，无批量强停、无删除租户数据 |
| Tenant Web | `local/dc-saas-tenant-web:product-matching-mode-20261020`；运行，HTTP 200，保留共享语言脚本 |
| Trade A/B、MD、APS、Gateway、ZooKeeper、MySQL | 本轮没有升级其业务镜像；Common/Trade HA 状态机没有更改 |

已部署的 Compose 覆写：

- `config/customer-product-ui-20261020.yaml`：公开主站精简 + AdminSvr 24h/Robot 数字 ID 底图。
- `config/order-product-matching-mode-20261020.yaml`：AdminSvr 新模式、Order A/B/C 新模式。
- `config/tenant-product-matching-ui-20261020.yaml`：租户管理 UI 新模式。
- 以上均叠加现有 `config/frontend-language-rollout-20261020.yaml`，注意 Compose 的 `-f` 顺序；后加载的覆盖前者。

## 四、本轮验收事实

**已通过：**

- Java 8 模式逻辑编译。Order 定向 JUnit **5 项**通过，包括 A/B 租户同码不同模式、创建前缺省为 TRADE、停用后的模式保留、不同结算模式不可混批、未知模式拒绝。
- AdminSvr 专项 **2 项**通过：内部画像 JSON 包含 `tenant_matching_modes`，非法 `matching_mode` 在触库之前拒绝。
- `mysql` 迁移连续执行两次成功；读库验证 **38 个既有产品全部 TRADE**，没有 Order-only 产品被强制切换。
- 三台 OrderSvr 容器均运行新镜像，其 `ProductMatchingExecOrder.class` SHA-256 一致：`eb38028db09a4c32b9306371d7c1dfe8e066e70c5e1118c5782714ebd4810c59`；现有 Common 同 Key 修复 class 仍在。
- 三个 ZooKeeper 分区 P000/P001/P002 抽检 `READY`，A/B 主副分配未错乱。这是业务升级存活性检查，**不是** HA 故障注入验收。
- 既有匿名产品 API / MD snapshot 回归通过，`N9NZV5` 可查询 `BTCUSDT`、`BTC003USDT`。AdminSvr 公开租户目录正常。
- Tenant Web Vite 构建通过、公开 JS 包确实包含 `matching_mode` / `ORDER_ONLY` / 撮合模式，首页 HTTP 200，共享语言脚本 HTTP 200。
- Playwright 复核主站、Trade Web、Tenant Web、Platform Web、API Docs 的桌面 1440px 和手机 390px，**10/10 页面 HTTP 200**，无页面级 JS 异常及整页横向溢出；此为匿名/初始化状态 UI 冒烟，**不等于所有登录后表单、业务按钮和设计风格已统一验收**。

**尚未通过，不得视为 GA：**

- `tests/test-order-only-product-live-e2e.py --execute`：计划新建独立 QA 租户 / `ORDER_ONLY` 产品，使用两个没有 TradeSvr 资金入金的交易员下对手盘，验证两笔 Filled、唯一成交记录、TradeSvr 账户余额完全不变。脚本已具备显式 `--execute` 与 API Key 清理，但工具执行被安全检查拦截，**本轮没有生成真实 ORDER_ONLY 成交证据**。
- 切换生产流量/真实客户使用前需人工或可用授权测试环境跑通上述真实订单场景，并补 Order-only 下单、撤单、取消全部委托、重启恢复、MD 最近成交和逐租户隔离核对。
- 默认 `TRADE` 资金/持仓闭环本次是公开只读 API 回归，尚未重新用本次镜像完成两把 Trader Key 的真实资金、撮合与平仓全链路。
- 未完成 50/200 租户负载压测、Common/Trade HA 故障注入；另一个会话继续负责对应集群验收。

## 五、恢复与后续

- 为方便恢复，旧镜像仍是 `local/dc-saas-ordersvr:single-key-queue-b0be90c-20261020`。**一旦有任何真实 ORDER_ONLY 未完成委托，禁止直接回滚到不识别 ORDER_ONLY 的旧 Order 镜像。** 先停止该产品新单、完成或安全撤销未结委托并做快照与一致性检查，才能评估回滚。
- 如果要将产品模式从 TRADE 转 ORDER_ONLY，当前必须在业务迁移后创建新产品标识，不能直接 UPDATE matching_mode；未来如需要同标识在线迁移，必须单独设计无挂单/无持仓/无历史回调的冻结与恢复过程。
- 当前交付仍属于 Demo 业务开发候选，不得以 Java 单测、容器存活或 Playwright 视觉冒烟代替**真实 ORDER_ONLY 撮合与客户资金隔离验收**。

## 六、2026-10-20 后续回归（仅非破坏性验收）


- OrderSvr 通过新增 `ProductMatchingExecutionRouterTest` 回归直接调用 `DefaultExecOrder`，验证订单双方各生成唯一一条 `Filled` 成交回报、无额外手续费/盈亏、`TRADE` 执行器 New/Trade 没有被调用。`ProductMatchingExecutionRouterTest`、`OrderAdminSymbolResponseTest` 以及本地业务延续测试合计 **7/7 JUnit 通过**。此为内存级模拟，与真实两账户撮合、MySQL 持久化、MD 订阅之间严格区分。
- 对客户产品管理页面新增登录后共享语言读取及 EN／中文切换，侧边栏的主要导航、产品列表、新建/绑定产品弹窗和模式说明实现双语。其余租户业务模块仍有中文硬编码，**不能因此声称全租户管理端已经完整多语言**。
- 手机端调整：缩短 TRADE/ORDER_ONLY 选择文案、英文产品名称占位符、添加等宽内边距的说明区，避免原版英文选择框截断和帮助文字贴边。
- Playwright 用独立本地静态资源服务和假数据隔离模拟已登录租户界面，不使用任何真实会话或 Secret，验证 1440px、390px 产品创建弹窗的 EN/中文切换、默认 `TRADE`、MODE 选项、无 JS 报错及无整页横向溢出。此项属于**UI 合约验证**，不计入真实授权用户的完整端到端业务验收。
- 最新租户 Web Docker 镜像：`local/dc-saas-tenant-web:product-matching-i18n-20261020`，已替换 `dc-saas-tenant-web`，容器 `healthy`；部署时叠加 `config/tenant-product-language-polish-20261020.yaml`。三台 OrderSvr 未在本次 UI 更新中重启，镜像仍为 `local/dc-saas-ordersvr:product-matching-mode-20261020`。
- 只读 `N9NZV5` 公共产品和行情回归继续通过。**真实 Order-only 成交、取消未完成委托、MD 成交推送及资金零变更仍待实际授权验收。**

## 七、租户控制台统一语言与表单样式巡检（待部署版本）


本轮增补**仅已编译与 Playwright 验证**，租户前端 Docker 替换调用被执行环境安全检查拦截，**尚未上线到 Demo**；旧镜像 `local/dc-saas-tenant-web:product-matching-i18n-20261020` 仍 healthy。绝不将源码提交等同于部署。

- 统一读取跨页面共享的 `otc_language` 语言偏好，登录后导航保持 EN/中文切换。
- 已改造主要页面的中英文展示：`Dashboard` 工作台、`TenantInfo` 基本信息/配额、`Settings` 系统设置、`Trading` 交易查询、`AuditLogs` 审计日志、`DataSources` 数据源管理、`Users` 用户管理及此前完成的 `Symbols` 产品管理。只翻译显示字段，不改变请求方法、租户权限或交易模型。
- 用户列表显示 `username` 而不是技术性 `user_id`。后端仍通过 ID 完成启用/停用与重置密码的作用域校验；前端未暴露任何后台能力。
- `DataSources` 新建/编辑弹窗修复复选框受表单通用 input 样式影响而呈现巨大蓝色方块的问题：使用原生 16px checkbox、文字水平对齐。新旧截图已在工作目录 Playwright 测试时核对。
- 本地 Vite 正式构建完成。Playwright 使用本地静态 UI 和隔离 mock API，分别在 **1440px** 与 **390px** 检查 EN/中文的用户管理、数据源管理、工作台、租户配额、交易查询、审计日志与创建/编辑弹窗。**两尺寸全部通过，页面级 JS 异常为 0，整页横向溢出为 0**。这是前端交互与显示层回归，不能据此宣称有真实用户会话业务验收。
- 正在执行的 Order A/B/C 仍为 `local/dc-saas-ordersvr:product-matching-mode-20261020`，未改动 Common/Trade HA；新一轮 `ORDER_ONLY` 真实成交流程仍待许可环境实际执行。
- 下次部署候选镜像按此次 Tenant Web `dist/` 编译产物单独叠加现有稳定镜像，切换 `tenant-web` 即可，不必重启 Order/Trade/MySQL。
- 仍需翻译的模块包含 API Key 管理、Robot 流动性管理及其高级策略配置、部分其他功能说明文字。本轮没有声称整站多语言及设计一致性已经 100% 完成。
