# 2026-10-21 租户中心与租户管理 OpenTradingCore Logo 返回主站

- 唯一功能修改：租户中心、管理员登录页、管理后台侧栏和手机顶部的品牌 Logo/文字设为可访问的 `https://opentradingcore.com/` 链接。租户注册/登录、业务菜单、交易终端入口及租户数据不变。
- 源码提交 `bliplink/dc-saas-tenant-web` 分支 `codex/tenant-delivery-polish-manual-20261020`，commit `3f5e9a3`。
- Demo 镜像：`local/dc-saas-tenant-web:brand-home-link-20261021`，在上一版 `mobile-nav-account-menu-20261021` 的基础上只覆盖 Vite 静态产物与两份同步更新的 PDF。
- 仅执行 `tenant-web` 的无依赖 Compose 重建（部署覆盖 `config/tenant-brand-home-link-20261021.yaml`），Order/Trade/MD/Robot/DB 均未重启。
- Playwright 用 mock 登录状态验证租户中心、登录页、已登录侧栏和手机 Logo 的 URL，390/768/1440px 全通过；租户管理中英文功能回归 3/3 PASS。
- 中文/英文图文手册增加 Logo 跳转说明，并重拍 Playwright 实际截图。新 PDF 分别 22 / 24 页，容器内 SHA256 与源码手册一致。
- 已验证公网：`https://tenant.opentradingcore.com/`、两份 `https://tenant.opentradingcore.com/help/OpenTradingCore_Tenant_Management_User_Guide_{ZH,EN}.pdf` 和目标 `https://opentradingcore.com/` 均 HTTP 200；tenant-web 容器 `healthy`。
- 后续全量 Docker/Compose 发布需包含本次源码和手册，以免恢复旧镜像后品牌链接丢失。本轮未声称 Robot 或 HA 验收通过。
