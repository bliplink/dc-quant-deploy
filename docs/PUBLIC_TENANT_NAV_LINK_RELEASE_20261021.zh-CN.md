# 2026-10-21 主站「租户」菜单 URL 更新

- **唯一的 Web HTML 更改**：主站桌面导航与手机抽屉中的 `data-i18n="nav.tenants"` 两条链接从 `#tenants` 改为 `https://tenant.opentradingcore.com/`。租户列表、分页、API、交易 CTA 和其他功能未改变。
- 源码提交：`bliplink/opentradingcore-web` 分支 `codex/homepage-i18n-production-review-20261021`，提交 `67a3df2`。
- 使用现有真实线上镜像 `local/dc-saas-public-web:customer-site-i18n-20261021` 作为基础，只覆盖 `index.html`；发布镜像为 `local/dc-saas-public-web:tenant-nav-only-20261021`。已逐字验证新旧 HTML 仅有两处 href 变化。
- 本次 Compose 覆盖 `config/public-tenant-nav-link-20261021.yaml`；部署只执行 `public-web` 服务替换，没有重启 Order、Trade、MD、Robot 或其他容器。
- 独立预发 + 实际运行后的 Playwright 1440/768/390px 回归全部 PASS：双语切换、API 文档语言 URL、Demo 交易链接、租户列表搜索和分页、两处租户菜单目标均正确且无浏览器报错。
- 发布后 `dc-saas-public-web-1` 状态 `healthy`；`https://opentradingcore.com/` 与 `https://tenant.opentradingcore.com/` 均返回 HTTP 200。实际运行页面 SHA256 与提交的 `index.html` 完全一致。
- 后续全量发布时应将该导航改动合入目标发布分支，不能因缺少本地镜像而意外回退。此处仅交付静态主站菜单的 URL 修正，不代表交易 HA 已恢复。
