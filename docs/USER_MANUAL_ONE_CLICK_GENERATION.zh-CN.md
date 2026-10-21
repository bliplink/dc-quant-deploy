# OpenTradingCore 六份图文手册一键生成

**唯一入口：** `./scripts/generate-user-manuals.sh`。

在 `dc-quant-deploy` 部署仓库（包含同级 `.work/dc-trade-web`、`.work/dc-saas-tenant-web`、`.work/dc-saas-platform-web` 源码）的根目录执行：

```bash
./scripts/generate-user-manuals.sh
```

一次生成六个 PDF：

| 界面 | 中文 | 英文 |
|---|---|---|
| 交易 Web | `OpenTradingCore_Trading_Web_User_Guide_ZH.pdf` | `OpenTradingCore_Trading_Web_User_Guide_EN.pdf` |
| 租户管理 | `OpenTradingCore_Tenant_Management_User_Guide_ZH.pdf` | `OpenTradingCore_Tenant_Management_User_Guide_EN.pdf` |
| 平台管理 | `OpenTradingCore_Platform_User_Guide_ZH.pdf` | `OpenTradingCore_Platform_User_Guide_EN.pdf` |

默认输出目录：`generated-user-manuals/YYYYMMDD-HHMMSS/`，同时包含 `OpenTradingCore_User_Manuals_all.zip` 和 `manifest.json`（页数、大小、SHA256、截图模式）。可以指定路径：

```bash
./scripts/generate-user-manuals.sh --output ~/Documents/OpenTradingCore-Manuals
./scripts/generate-user-manuals.sh --scope trade
./scripts/generate-user-manuals.sh --scope tenant
./scripts/generate-user-manuals.sh --scope platform
```

## Playwright 截图刷新

默认使用仓库已保存、经过人工验收的 Playwright 截图，**不访问带凭据的服务、不创建租户、不充值、不下单**。后续修改了 Web 界面时，应先核对各手册章节，再按需要重拍：

```bash
# 用当前交易终端匿名页面截图 + 实际平台 Web 的只读演示数据截图更新素材。
./scripts/generate-user-manuals.sh --capture
```

平台截图通过 Playwright 加载真实部署的 UI，拦截 `/httpapi` 并返回**明确的非生产示例数据**，不会修改线上平台配置；英文版手册使用英文操作说明、实际中文界面截图，当前平台 Web 尚不支持完整英文 UI。交易 Web 的普通截图来自真实公开行情。

若确实需要重新拍摄登录状态和租户管理内的表单，**这两类截图过程会创建 Demo 测试账户或租户**，仅在可写、隔离的 Demo 环境明确授权后运行：

```bash
./scripts/generate-user-manuals.sh --capture-tenant-live --allow-demo-writes
./scripts/generate-user-manuals.sh --capture-trader-login --allow-demo-writes
```

涉及真实交易和资金的操作不在手册截图任务中执行。完成新截图后，需检查是否包含真实密码、Secret、Token、API Key、客户个人资料。平台集群截图中的示例健康数据**不是**真实的 HA 验收结果。

## 前置条件

- Mac：Python 3、Node.js、Google Chrome、macOS PDFKit (`swift`)，或其他平台安装 `pdfinfo`。
- 交易 Web 提供专用的 Playwright 依赖：`npm ci --prefix .work/dc-trade-web/qa/guide-tools --ignore-scripts`。
- 租户/平台生成器可共用 `.work/site-playwright-qa/node_modules` 的 Playwright（本机已有）。首次新机需要先在该目录安装 Playwright，或设置环境变量 `NODE_PATH` 指向可用 Playwright 包。
- 若 UI 源码仓库不在标准 `.work` 目录，指定 `--repo-base /path/to/the-three-ui-repos`。

## 生成与发布是两件事

一键脚本**只生成/校验本地 PDF，不修改 Docker 运行镜像、不发布公网、不重启 Order/Trade/MD**。发布时再按三个 Web 的镜像/配置单独将对应手册复制到 `/help/`，核对 URL、内容类型、SHA256 与网页版本一致。只有手册与界面在同版完成，才能宣布页面交付完成。

手册源码位置：交易 `dc-trade-web/docs/user-manual/trading-web/`、租户 `dc-saas-tenant-web/docs/` 与 `public/help/`、平台 `dc-saas-platform-web/docs/user-manual/`。统一发布规定见 `docs/FRONTEND_USER_MANUAL_SYNC_POLICY.zh-CN.md`。

## 本轮实测

2026-10-21，`./scripts/generate-user-manuals.sh --scope all --output ../generated-user-manuals/all-20261021` 返回成功，生成交易 13/9 页、租户 21/21 页、平台 7/7 页，中英文共六份。每份都通过系统 PDFKit 真实页数和 PDF 文件检查，ZIP 与 manifest 生成成功。
