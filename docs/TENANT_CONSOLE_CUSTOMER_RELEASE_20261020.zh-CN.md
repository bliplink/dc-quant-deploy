# 2026-10-20 租户管理对外交付发布

目标：不触碰 Common、Order、Trade、MD 集群，改进租户管理 Web 的正式用户体验，并发布中英文租户管理员手册。

源码：`bliplink/dc-saas-tenant-web` 分支 `codex/tenant-delivery-polish-manual-20261020`，提交 `a4b9fde`（已远端推送，`[skip ci]`）。源码包含前端实现、`docs/TENANT_MANAGEMENT_USER_GUIDE.{zh-CN,en}.md`、静态 `public/help/{zh,en}.html`、`qa/tenant-delivery-browser.cjs` 与 `qa/tenant-delivery-live.cjs` 及详细验收矩阵。

Demo 镜像：`local/dc-saas-tenant-web:customer-ready-bilingual-guide-20261020`（本地 Docker image `sha256:e85fcf9afe1b1246aa9b80f06b5730029b79322aaf24a5e7ecd3850442be1563`）。Compose override: `config/tenant-customer-ready-guide-20261020.yaml`。只重建 `tenant-web`，容器 `dc-saas-tenant-web` 健康检查 `healthy`，Order A/B/C、Trade A/B、MD A/B/C 保持原运行时间，没有停止、故障注入或修改 Common。

公网页面：`https://tenant.opentradingcore.com/help/zh.html` 及 `https://tenant.opentradingcore.com/help/en.html`，HTTP 200。

真实浏览器测试完整 PASS 租户：`B36KVV`。通过创建/自动审批、租户管理员登录、创建用户、自定义数据源、自定义产品及纯撮合模式绑定、Broker Key 创建/Secret 一次显示/撤销、交易查询/资金流水/审计/设置导航、中文切换和 390px 手机视口。桌面及手机模拟 API 回归：1440/768/390px，页面总宽未溢出、JS 错误 0。其他 QA 租户不作为正式业务案例。

未验收事项：真实 Robot 启停与模板变更后持续交易、运营级性能，以及全部 HA、快照/WAL、自动恢复/主切和 50/200 租户负载测试。下一阶段等待 Common 更新以后统一开展集群验收。

发布时不使用 GitHub Actions；镜像在 Mac 本地打包。之后正式发布应使用仓库原生 `Dockerfile` 从相同源码重新构建、先跑 QA，并更新 Compose 的固定镜像版本，不以此本地 overlay 镜像取代正式 CI 构建流程。

## v2 双语表单验收增补

源分支追加提交 `e87fa2d` (`[skip ci]`)；正式 Demo 前端镜像更新为 `local/dc-saas-tenant-web:customer-ready-bilingual-guide-v2-20261020`，镜像 ID `sha256:14ce52f11957b35a2791b43ae92dc238bb5ab444a0f89be273b7e7856ce9279a`。重建范围仅租户 Web。解决流动性模板、机器人新增/编辑的校验错误中文硬编码和应用模板确认消息的语言错误。使用已部署容器（不是仅本地 dist）对中英文提交错误，以及 1440 / 768 / 390 像素页面进行了浏览器回归，全部通过；无 JS 异常、无页面级横向溢出。中英文公网用户手册 HTTP 200，tenant-web health `healthy`；Common/Order/Trade/MD 集群保持未改动。
