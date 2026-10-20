# 租户后台用户名和流动性界面发布验收｜2026-10-20

## 发布范围

- 管理接口查询修复：`AdminSvr` 的 `TenantTraderApiKeyService` 只读 Trader Key 列表通过 `dc_users_api.location + user_id` 与 `dc_users` 的同租户用户表连接，仅新增 `user_name` 白名单列，不查询 Secret、密码或 Robot 原始凭证。内部 `user_id` 保留以保障稳定关联和去重，不再作为用户 Key 表格的可见主标题。
- 租户前端修复：显示 `row.user_name`（缺失时 `--`，不擅自回退展示内部 ID），并统一 API Key、Robot 运行管理、Liquidity Profile 主要 UI 标签、表格、弹窗、确认和帮助信息的 EN／中文支持，使用此前的 `OTCSharedLanguage` 语种状态。
- 本轮**没有变更**任何 Robot 运行和下单参数、API Key 权限、撮合策略、Common、Order/Trade/MD 的 HA 或 WAL 机制；已有容器数据未清理。

## 真实运行镜像

| 服务 | 镜像 | 说明 |
| --- | --- | --- |
| `dc-saas-adminsvr` | `local/dc-saas-adminsvr:trader-key-usernames-20261020` | 以现有 `product-matching-mode-20261020` 镜像为基础，仅覆盖经过 JUnit 验证的 `TenantTraderApiKeyService.class` |
| `dc-saas-tenant-web` | `local/dc-saas-tenant-web:unified-admin-bilingual-20261020` | 以现有 `product-matching-i18n-20261020` 镜像为基础，仅覆盖 Vite 编译的前端静态资产 |

Compose 覆盖文件：`config/tenant-admin-bilingual-usernames-20261020.yaml`。两项服务分别以 `up -d --no-deps --force-recreate` 替换；Order A/B/C、Trade A/B 未重启。回退时分别使用上述旧镜像标签，并单独重建各自服务即可。

## 验收证据

1. 原生 Java 8 `javac` 编译 + JUnit4：**3/3**，覆盖用户名映射、同租户 SQL JOIN、Secret 掩码和列表去重。Demo MySQL **46 条交易员 Key 均能关联用户名（46/46）**。此项验证了 SQL 数据，但未代替有权限会话的端到端响应校验。
2. AdminSvr 运行容器中的 `.class` 与本地通过测试的新 `.class` **字节一致**。新容器启动成功；启动冷却阶段一次公开查询曾返回业务码 `9000`，启动稳定后 `publicTenantDirectory` 响应 **HTTP 200 / 业务码 0 / NO_ERROR**。AdminSvr 无单独的 Docker healthcheck，不据此宣称其所有管理接口均通过。
3. 租户前端 Vite 生产构建成功，Docker 实际 JS 包验证包含新翻译。容器已达 `healthy`，`https://tenant.opentradingcore.com/` 返回 HTTP 200。
4. Playwright 以部署的真实静态页面 + **隔离模拟已登录用户和接口数据**分别在 1440px 与 390px 检查：工作台、用户管理、产品、数据源、API Keys、Robot、流动性模板、交易查询、审计日志、系统设置、英语/中文切换，以及创建 API Key、Robot、Liquidity Profile 的弹窗。**均通过；JS 页级错误 0；整页横向溢出 0**。模拟交易员 Key 列表验证只显示 `demo-trader` 用户名，不显示 `internal-user-id-not-public` 技术 ID。
5. 保留配置修改权限、SECRET 仅显示一次、交易写权限明确 opt-in 的原有安全逻辑。未尝试执行真实建 Key、启动 Robot 或提交交易写请求。

## 未完成的生产验收

- **真实有权限账号**访问 `tenantTraderApiKeyList` 并确认真实用户 Key 列表显示正确用户名仍需人工/自动化登录验收；测试中的是模拟响应，不能替代该项。
- Robot 编辑页与流动性模板的**部分高级标签、动态错误代码和运营术语**仍未全面本地化，亦未完成视觉精调到所有模块 100% 一致。现有 1440px/390px 检查主要验证关键交互和是否溢出，尚需人工逐屏确认。
- 最新 SDK `0.1.6` 的公共 Gateway 已确认握手和订阅 ACK；连续行情通知、私有余额/持仓/订单/成交推送及断线追平仍缺真实端到端证据。本轮未使用密钥执行私有订阅。
- Order-only 模式尚未完成两名未入金交易员的真实成交、MD 推送和资金零变更验收。Common/Trade HA 由另一会话验证。

## GitHub 交付分支

- `bliplink/adminsvr`：`codex/tenant-trader-key-usernames-20261020`，提交 `b1c1e77`。
- `bliplink/dc-saas-tenant-web`：`codex/tenant-product-matching-ui-20261020`，提交 `da53a81`。
- `bliplink/dc-quant-deploy`：`codex/tenant-admin-bilingual-usernames-release-20261020`，本报告与 Compose 覆盖配置。

以上分支均为独立交付，不覆盖当前远端 `saas-crypto`，应由负责合并的会话在统一镜像中整合、再次回归。
