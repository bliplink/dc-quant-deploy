# 2026-10-21 租户管理手机端 UI 更新部署记录

- 本次仅更新 `dc-saas-tenant-web`，没有触碰 Order、Trade、MD、Robot、MySQL 或其他服务。
- 源码分支 `bliplink/dc-saas-tenant-web:codex/tenant-delivery-polish-manual-20261020`，提交 `820bf33`；演示镜像 `local/dc-saas-tenant-web:mobile-nav-account-menu-20261021`（Docker SHA `d1315d0621f2`），以线上既有静态镜像为基础叠加新 Vite 产物及手册。
- 部署覆盖文件 `config/tenant-mobile-console-20261021.yaml`，只指定 `tenant-web.image`。结合运行环境中经过校验的当前 Compose 配置，仅替换 `tenant-web`，不默认重建依赖服务。
- 变更：手机端左侧抽屉导航、头像账户菜单中的语言偏好、卡片列表、移动端编辑弹窗；系统 Robot 用户 `market-maker` 和 `tape-trader` 仅以做市账户/点价账户友好展示，保留原始用户名和 Key 绑定。
- Playwright 通过 `390/768/1440` 宽度移动抽屉/语言/用户卡片测试；既有租户双语功能回归三种宽度均 PASS，生产构建 PASS。独立临时镜像静态文件/PDF/健康检查 HTTP 200；实际线上 `tenant-web` 替换后容器 `healthy`，公网主页及中英文 PDF HTTP 200，PDF 内容类型 `application/pdf`，中文 2,150,739 字节、英文 1,724,788 字节，PDFKit 均确认 23 页。实际运行镜像被再次执行浏览器双语回归 3/3 PASS。
- 中文手册：https://tenant.opentradingcore.com/help/OpenTradingCore_Tenant_Management_User_Guide_ZH.pdf
- 英文手册：https://tenant.opentradingcore.com/help/OpenTradingCore_Tenant_Management_User_Guide_EN.pdf
- Demo 的 Robot、Order/Trade 物理复制异常仍属于另一条集群验收工作，不得将本次 UI 交付等同于交易业务恢复。
- 后续重新构建全量生产镜像时须将新增前端和两份手册打包，并审查当前 `saas-crypto` 目标分支与新镜像对应关系；此 local overlay 镜像仅适用于本次 Mac Demo。
