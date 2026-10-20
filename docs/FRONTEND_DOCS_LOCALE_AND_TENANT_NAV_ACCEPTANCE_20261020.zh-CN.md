# 主站 API Docs 链接随语言切换、交易核心租户导航统一：部署与验收

日期：2026-10-20。只修改主站和交易终端的静态前端，不调整 Order/Trade/MD/APSSvr/Common HA 状态机。

## 功能变更

1. 主站三处 API 文档入口（PC 顶部导航、移动端菜单和首页 API 介绍）统一标注 `data-api-docs-link`，页面启动、下拉框修改、跨页共享语言事件时根据语言设置链接：中文 `https://api.opentradingcore.com/zh/`，英文 `https://api.opentradingcore.com/en/`。不允许链接停留在无语言的根路径。两个链接已通过外部 HTTP 200 测试。
2. 交易核心顶部导航和交易员登录页的“租户中心 / Tenant Portal”统一成“租户 / Tenants”，与主站导航文案相同。保留原有跳转逻辑和目标租户 location 参数，没有新建后台路由或改变权限。
3. 统一语种保留既有 `.OTCSharedLanguage` 的同域共享状态与 `otc-language-change` 通知；保留主站此前完成的租户代码直达交易终端、Status/Action 两列精简、24h 最新数据展示等修正。

## Demo 本地镜像（已替换运行）

- 主站 `dc-saas-public-web-1`: `local/dc-saas-public-web:api-links-locale-20261020`，基于上一版 `customer-ui-v2-20261020`，只覆写 `index.html` 和 `assets/js/site.js`。
- 交易终端 `dc-saas-trade-web`: `local/dc-saas-trade-web:tenant-nav-label-20261020`，基于上一版 `shared-language-safe-20261020`，只覆写 webpack 构建结果，保留现有 charting_library、共享语言脚本和 Nginx 配置。
- Compose 覆盖文件：`config/frontend-docs-tenant-label-20261020.yaml`，在 `compose.yaml`、`config/frontend-language-rollout-20261020.yaml` 及适当业务前端覆盖之后加载；使用 `--no-deps --force-recreate` 仅替换 `public-web`、`web`。
- 两个容器最后检查均 `healthy`。Order A/B/C、Trade A/B、AdminSvr、MD、APS、MySQL 及 Common HA 不在本轮升级范围。

## 浏览器与接口验收

- 主站 Playwright 本地源码：PC `1440x850`、手机 `390x850`，3 个 Docs 入口均覆盖：EN→中文、中文→EN、移动端选择、共享偏好变更、刷新与 `?lang=` 初始化，全部通过，无页面级 JS 异常。
- 运行中 Demo Playwright：相同 PC/手机视口，主站 3 个入口 EN / 中文 URL 均正确；交易终端 PC/手机的 `Tenants` 与 `租户` 文案均出现，未显示旧“租户中心”；无页面级 JS 异常，document.scrollWidth 不超出视口；PC 与手机 4 个组合通过。
- 正式主站 `https://opentradingcore.com/?lang=zh-CN` 外部 GET 已包含 3 个 `data-api-docs-link`；正式 Docs EN / ZH 均为 HTTP 200。
- **受网络/代理环境影响，Mac 命令行访问 `https://trade.opentradingcore.com/` 曾出现 TLS 连接 reset（HTTP 000）；本地 Docker 静态网页返回 200、Playwright 访问正常。不能仅据此判断全球用户访问情况已通过，需用外网浏览器另行复核。**

## GitHub 源代码交付

- `bliplink/opentradingcore-web` 独立交付分支 `codex/api-docs-links-shared-language-20261020`。
- `bliplink/dc-trade-web` 独立交付分支 `codex/trade-tenant-nav-20261020`。
- `bliplink/dc-quant-deploy` 独立交付分支 `codex/frontend-docs-language-tenant-nav-20261020`。
- 由于本地部分 `saas-crypto` 与 origin 已分叉，不强制推送，不覆盖原远程 `saas-crypto`，源码审查后通过 PR / cherry-pick 合并。

## 仍待完成

- 租户控制台工作台、用户、数据源、订单等后续双语修订已完成编译、Playwright 模拟登录验证并推至 `bliplink/dc-saas-tenant-web` 分支，但上一轮对应容器替换受到执行环境安全检查拦截，**最新批次尚未在 Demo 上线**。
- Robot/流动性管理与 API Key 后台模块剩余静态中文文案，生产化 UI 全面验收仍需补齐。
- `ORDER_ONLY` 无 Trade 资金路径的两未入金交易员真实成交/撤单/资金零变更验收仍未获得实际执行证据；内存 JUnit 不是端到端交易证明。
