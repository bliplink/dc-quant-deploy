# 交易 Web / 租户 Web / 主站“租户”文案与租户入口按钮验收｜2026-10-23

## 需求

- 租户 Web 公开入口的“创建租户”与“租户登录”按钮桌面端保持相同顶部位置、高度和宽度。
- 交易 Web、租户 Web、主站可见的“租户中心”统一改为“租户”；英文同类标签 `Tenant Portal` 改为 `Tenant`。不是要移除语义正确的“多租户”或“租户控制台”等其他词语。

## 原因与代码

- 根因：`dc-saas-tenant-web/src/styles.css` 的 `.login-card .primary { margin-top:8px }` 使创建租户（primary）按钮比并列的租户登录按钮低 8px。
- 修复：增加 `.portal-choice.primary { margin-top:0; width:100% }`，其选择器与前者等权重、加载顺序靠后，保证同一排两个按钮顶部一致，同时不改其他表单主按钮。
- 租户 Web：`bliplink/dc-saas-tenant-web/saas-crypto@f48dc71`（远端最新代码上 cherry-pick 的修复），只更新 `src/main.jsx` 与 `src/styles.css` 的入口文本及间距。
- 交易 Web：`bliplink/dc-trade-web/saas-crypto@5e0c793`，只更新 `src/pages/header/Header.jsx`、`src/pages/login/index.jsx` 两个文案。
- 主站 `opentradingcore-web`：检查当前源码和在线 HTML，无 `租户中心` / `Tenant Portal` / `Tenant Center`，已有正确“租户”“多租户”导航，不需更新主站镜像。

## 部署与回退

- 保留原有运行镜像、品牌入口、用户指南和其他功能；单独重建 `web` 与 `tenant-web`，未动后端或主站。
- 租户 Web：`local/dc-saas-tenant-web:tenant-labels-aligned-20261023`，仅在已运行基线 `brand-home-link-20261021` 上修补活跃 JS/CSS 和引用的资源名。新增 Override：`config/tenant-entry-labels-20261023.yaml`，父配置 `.work/deploy-live-qa-export-20261020/config/tenant-brand-home-link-20261021.yaml`。回退到 `brand-home-link-20261021`。
- 交易 Web：`local/dc-saas-trade-web:tenant-label-only-20261023`，基于 `order-entry-20261023` 镜像替换最新构建 Web bundle。新增 Override：`config/trade-web-tenant-labels-20261023.yaml`，保留前面的使用手册、Tab、下单表单 Override。回退到 `order-entry-20261023`。

## 实机验证

- Docker：`dc-saas-trade-web` 与 `dc-saas-tenant-web` 均 healthy；公开域名载入新的静态资源，两个使用手册文件仍在。
- Chrome 桌面 1280×900：英文“Create Tenant/Tenant Sign In”、中文“创建租户/租户登录”均同一顶部坐标 `261.828125`、高度 `72px`、宽度 `219px`，主按钮上边距为 `0px`。租户首页标题在中文是“租户”、英文是“Tenant”。
- Chrome 390×844：按预期上下排列，两个按钮均高 `62px`、宽 `320px`，左侧对齐。
- 交易 Web 浏览器：导航为 `Trade / Tenant`，页面不再显示“租户中心”或 `Tenant Portal`。
