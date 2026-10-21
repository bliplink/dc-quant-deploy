# OpenTradingCore 前端与用户手册同步交付规定

**生效日期：2026-10-21。适用：主站、交易 Web、租户管理 Web、平台对客页面，以及 API Docs 中面向用户的使用流程。**

## 一条硬性规定

> **凡是改变用户实际看到或操作到的页面，就必须在同一个变更/发布批次内检查并同步用户手册。用户流程、界面文案、图标位置、菜单、表单、交互、按钮行为、产品展示、登录注册、权限及 PC/手机布局的变化，都属于本规定范围。涉及界面变化时，必须用 Playwright 重新拍摄受影响部分的真实截图，并更新 PDF。没有同步手册、截图和发布验证的页面改动，不视为交付完成，不应上线。**

## 适用手册与归属仓库

| 页面 | 文档源、截图与 PDF | 公网正式入口 |
| --- | --- | --- |
| 交易 Web（PC / 移动端） | `bliplink/dc-trade-web`: `docs/user-manual/trading-web/`，中文源 HTML、Playwright 截图和 PDF；版本随交易 Web 镜像发布 | `https://trade.opentradingcore.com/help/OpenTradingCore_Trading_Web_User_Guide_ZH.pdf` |
| 租户管理 Web（中文 / 英文） | `bliplink/dc-saas-tenant-web`: `docs/TENANT_MANAGEMENT_USER_GUIDE.{zh-CN,en}.md`，`docs/screenshots/`，`public/help/OpenTradingCore_Tenant_Management_User_Guide_{ZH,EN}.pdf` | `https://tenant.opentradingcore.com/help/OpenTradingCore_Tenant_Management_User_Guide_ZH.pdf`、`..._EN.pdf` |
| 主站 | `bliplink/opentradingcore-web`: `docs/PUBLIC_SITE_USER_MANUAL_IMPACT.md` 记录用户入口/流程影响及对应截图。若改动影响交易或租户操作步骤，必须同步修改上述相应 PDF，并记录关联源码提交 | 主站不是独立交易员/租户操作手册；入口、语言与操作指引必须和对应两份手册一致 |
| Python API Docs / SDK | `bliplink/opentradingcore-api-docs`: 同步 SDK 方法、真实示例与文档；若涉及用户 Web 创建 API Key/开户/操作流程，必须同步上述相应 PDF | `https://api.opentradingcore.com/zh/` 和 `/en/` |

## 统一一键生成

每次需要重新生成六份图文 PDF，运行 `./scripts/generate-user-manuals.sh`。详细用法和安全选项见 `docs/USER_MANUAL_ONE_CLICK_GENERATION.zh-CN.md`。生成不会自动上线，发布前仍必须完成截图及同版验收。

## 每次页面修改必须执行的步骤

1. **识别手册影响**：在编码阶段指出受影响的页面与章节；增加/删除功能时同步增加/删除说明，调整名称时更新中英文用词及截图。
2. **实际截图**：在已部署的对应版本或可复现的隔离 Web 上，用 Playwright 截取改动后的界面。必要时同时捕获 1440px PC、390px 手机及登录/匿名状态。不得用设计稿或旧截图冒充当前线上界面，不能包含密码、API Secret、Session、真实客户资料。
3. **更新文档源与 PDF**：文字、截图、页面导航及步骤必须一致。租户管理对已有中英文手册两份都检查；交易 Web 更新中文版，新增英文版后同样执行双语同步。
4. **实际核对**：复查截图内容、PDF 的每页中文/英文显示、溢出裁切、文字可检索、页数、链接及所述行为。不能通过省略异常或伪造行情/余额来保证截图好看。
5. **同批次提交与发布**：UI 代码变更与文档源、截图、PDF 一起提交审核；**不能先发 UI、过几天再补手册**。部署后验证 PDF HTTP 200、`Content-Type: application/pdf`、文件 SHA/大小、Web 容器 health。
6. **发布门禁**：在变更前的基准提交上运行 `python3 qa/check-user-manual-sync.py --project trade|tenant|public --base <UI变更前的提交>`。失败禁止发布。主站还需对照对应交易/租户手册进行人工交叉验证；当前 GitHub Actions 配额不足，以本地检查为准，不声称 CI 自动拦截已执行。

## 开发、评审与验收责任

- 前端开发与修改页面的助手负责**同时维护手册**；测试人员负责 Playwright 截图准确性与 PDF 可读性；发布者负责核查公网版本及手册与页面同版。
- 单元测试通过、HTTP 200、页面打开或业务服务运行均不能单独替代手册验收；手册也不能替代 Trade/Order 的真实业务或 HA 验收。
- 无用户可见影响的纯内部变更，无需强行重制 PDF，但需要在变更说明中给出具体理由和复核。不能用“仅 UI 微调”作为豁免理由，视觉微调同样要同步对应截图。
- 不得在手册中把尚未通过验收的 Trader/Broker 入金、真实撮合、复制恢复等流程描述成生产已经验收成功。

## 发布完成标准

**功能验收 PASS + 对应手册文字准确 + Playwright 新截图 PASS + PDF 排版检查 PASS + 同版公网链接 PASS，全部满足才允许宣布页面交付完成。**

本规定为后续多会话开发的一致交付约束。各 Web 仓库的根目录 `AGENTS.md` 包含同一要求；`qa/check-user-manual-sync.py` 是可在 Mac 本地执行的差异门禁。
