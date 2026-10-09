# 管理控制台功能与移动端验收报告 — 2026-10-09

## 环境与范围

- Git 分支：`saas-crypto`。演示环境：Mac mini / Colima / Cloudflare Tunnel。
- 租户控制台：`ghcr.io/bliplink/dc-saas-tenant-web:sha-a0cfb6fe171bab11648ebcb141f697dd48314e1a`。
- 平台控制台：`ghcr.io/bliplink/dc-saas-platform-web:sha-e86949b474c57dd9c207643fab77960e89c5c027`。
- 隔离 QA 租户：`DPGR6B`；私有测试凭据位于 Mac mini 的 `~/.opentradingcore/management-qa-fixture.json`（权限 `0600`），不纳入 Git。
- 测试：真实 headless Chromium、正常管理端登录、界面交互和后端数据核对。没有代替真实浏览器的 HTML 文本检查。

## 本轮缺陷与修复

| 问题 | 复现 | 处理和结果 |
|---|---|---|
| 768px 竖屏整页横向溢出 | 租户页面宽 980px、平台页面宽 1180px | 响应式断点扩展至 1024px，均回归为 768px |
| 手机管理侧导航高度不稳定，留白过多 | 某些页面移动端导航可占 333px | 管理 Shell 显式定义内容行，压紧导航与底部信息；复看截图 |
| 平板 4 个统计指标纵向单列 | 768px 内容空间利用不佳 | 600–1024px 时统一两列指标卡 |
| 小字和触控目标 | 移动端部分标签 12px、按钮 34px | 管理表单标签 13px，主操作按钮与导航 44px，状态文字 12px |
| 数据管理表横向溢出 | 多列表格宽于手机 | 仅表格区域允许左右滚动，页面整体不再横移 |

**风格**：租户端延续蓝色操作强调色、平台运营端延续琥珀色；系统优先使用 Inter、PingFang SC、Microsoft YaHei 和系统回退字体，不新增在线字体依赖。

## 实际浏览器验收

三个设备尺寸：390px 手机、768px 平板、1366px 桌面。

- 租户端（每设备各 8 页）：工作台、用户管理、交易查询、品种管理、Robot 管理、租户信息、审计日志、系统设置。
- 平台端（每设备各 3 页）：租户审批、租户管理、集群管理。
- 合计 **33/33** 组页面检查通过：管理会话登录成功、目标页面渲染、整页无横向溢出、无 JavaScript pageerror、无应用错误提示、移动导航按钮达到最小 44px。
- 登录布局还曾单独检查 320/390/430/720/768/820/1024/1366px 两端共 16 组，无水平溢出。

功能回归：

- 独立 QA 租户由完整 E2E 自动申请、审批、Maker 20+20、Tape 初始化、入金、开仓、平仓与持仓归零。
- 真实浏览器：租户管理账号登录；用户创建 **PASS**、禁用 **PASS**、启用 **PASS**、密码重置 **PASS**、新密码通过 `LoginSvr` 重新登录 **PASS**。
- 平台管理员：真实浏览器登录、审批列表、租户列表、集群管理页面 **PASS**；本次只读，不更改现网集群拓扑。
- 既有回归：`tenantUserAdmin LIST`、`tenantRobotAdmin LIST`、`tenantSettingsAdmin GET/AUDIT` 与跨租户访问被拒绝均已验证（本次未重复执行全部写操作）。
- 测试租户实际配额为 2 个可注册用户，首次创建成功后重试创建触发预期配额拒绝；后续改为复用已有 QA 用户，未放宽限制。

**尚未验收通过**：Robot 新增/编辑/启停写操作；平台审批状态写入；租户路由修改、回滚；集群 Placement 发布；手机端真实物理设备手势/键盘/软键盘遮挡；高并发管理后台性能。这些项目需要单独的隔离环境、权限确认或专门的可恢复测试，不能由这次 33/33 页面验收代替。

## 证据与复跑

截图及 JSON 报告（保留在 Mac mini，不含管理员密码）：

`/Users/kong/.opentradingcore/dc-saas-runtime-fresh2-20261005/e2e-artifacts/management-qa-20261009/`

- `qa-results.json`：33 个页面与设备的结果（最新 `QA_ONLY_UI=1`）。
- `tenant-*.png`、`platform-*.png`：手机/平板/桌面登录后各页截图。

复跑前将 Mac mini 的正式部署 `.env` 导入环境。对于已经建立的 QA fixture，可执行：

```bash
QA_ONLY_UI=1 python3 tests/run-management-mobile-qa.py
QA_ONLY_CRUD=1 python3 tests/run-management-mobile-qa.py
```

如需**新建**一个隔离测试租户，需明确指定 `MANAGEMENT_QA_CONFIRM=YES` 后执行 `tests/create-management-qa-fixture.py`；它会增加一个试用租户和 Robot，不应用于生产租户。

## 状态限制

以上说明的是 Demo 环境的即时验收快照，不是 200 租户容量测试结果。UI 及管理功能重建过程中，仅替换租户与平台 Web 容器，未重启 Order/Trade 核心节点；仍应继续执行 Projection / Order HA 一致性检查。
