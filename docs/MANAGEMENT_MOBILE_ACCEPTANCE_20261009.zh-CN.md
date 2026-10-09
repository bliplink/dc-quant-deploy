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

**第一轮尚未覆盖（截至页面布局验收时）**：Robot 新增/编辑/启停、平台审批状态写入、租户路由修改/回滚、集群 Placement 发布、物理设备软键盘及高并发管理压力。部分项目已在下方“追加验收”完成，其余仍明确列为待办。

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

## 设计细节待确认

- 平台运营端当前仍使用 `DC` 标志与固定中文文案；租户端使用 OpenTradingCore 标识并支持中英文切换。两者的蓝色/琥珀色角色强调色有意区分，但**品牌标志及平台多语言统一**尚未作为本轮变更，应由产品确认再调整。
- 手机端导航为横向滚动，能够访问所有栏目，但首次用户不一定注意可滑动；后续可考虑增加轻量的滑动提示。
- 平台租户页有“已注册/启用用户”统计与“配额”两个数字，其计算口径（是否包含平台/流动性系统账户）需要专项核实；本轮未更改计数逻辑。

## 追加验收：平台审批、Robot 详情及隔离租户启停（2026-10-09）

### 平台审批与租户配置写操作

`tests/management-platform-approval-acceptance.js` 通过真实 Chromium 浏览器及正式接口执行，全部通过：

- 平台管理员真实登录及会话校验。
- 用 `example.invalid` 虚拟联系邮箱新建两条申请：`NEEDS_INFO`、`REJECTED` 审批分别成功，随后从 `tenantApproval LIST` 确认持久化状态。
- 仅对隔离租户 `DPGR6B` 修改租户名称并保存，然后重新打开、恢复原名称，两次操作均通过。
- 集群管理只读拓扑通过；未发布 Placement、未修改任何业务分区或服务路由。

### Robot 详情真实故障修复

- 初次点击详情失败，ManagerSvr 日志报 `Unknown column 'side' in 'field list'`。
- 根因：`RobotOperationalMetricsService.positions` 旧 SQL 假设 `dc_orders_position` 有 `side,size` 行模型，实际投影表使用 `long_position,short_position` 双列。
- 修复：`COALESCE(SUM(COALESCE(long_position,0)-COALESCE(short_position,0)),0)`，保持按 `location,security_id,user_id` 过滤；增加 `RobotOperationalMetricsServiceTest` 并在 ManagerSvr GitHub Actions 中显式执行。
- 代码：`bliplink/com.app.dc.managersvr@1a9011e`。CI 构建和单测通过，正式镜像 `ghcr.io/bliplink/managersvr:sha-1a9011e22201467b59875a53d10fbdc8df7779ff` 已上线。
- 真实浏览器复测 `robotMonitor DETAIL` 通过：运行 `RUNNING`、40 挂单、库存 `NORMAL`、Maker 与 Tape 仓位相反、净库存 `0`。

### 隔离 QA Robot 停止与恢复

- 单独 QA 租户 `DPGR6B`，不影响其他租户；真实管理 UI 的 `STOP` 成功，配置 `enabled=0` 已确认；恢复前遵守运行 Owner 的撤单与释放栅栏。
- 真实 UI 的 `START` 返回成功；首次自动验收对配置列表执行 `RUNNING/40` 轮询超时，导致脚本记为 FAIL，但随后的权威数据库查询确认 `enabled=1,runtime_status=RUNNING,open_order_count=40`，心跳新鲜且无错误码。
- 修订测试脚本改用 `ManagerSvr.robotMonitor LIST` 运行态读接口；**只读独立复验 PASS**：Robot 详情成功，运行监控确认 `RUNNING/40`。为避免无谓的再次撤单，本轮没有为了单次脚本全绿重复停止。
- 全局复核：**12/12 Robot RUNNING/40**、初始化失败 0、Order HA 快照与分区一致、Projection Trade/Order watermark mismatch 均为 0。

### 留待完成与风险边界

- `Robot UPSERT`（新增、参数修改，需要安全处理敏感凭证）**尚未通过写操作验收**；仅 Robot 详情/停止/启动/恢复已分别验证。
- 平台 `APPROVE` 批准并开通新租户路径尚未由本轮平台浏览器流程完整执行；此前自动审批的注册交易 E2E 不等同于平台 UI 手工批准。
- 服务路由真实修改/回滚、Placement 发布、真实设备软键盘/手势、高并发管理后台压力测试，仍需隔离计划，不应在多租户 Demo 正常交易时直接执行。

### 可重复执行

预先导入 Mac mini 私有部署环境，不要将 `.env` 或 QA 凭据写入日志。

```bash
MANAGEMENT_QA_SCRIPT=management-platform-approval-acceptance.js python3 tests/run-management-mobile-qa.py
QA_DETAIL_ONLY=1 MANAGEMENT_QA_SCRIPT=management-robot-control-acceptance.js python3 tests/run-management-mobile-qa.py
QA_VERIFY_ONLY=1 MANAGEMENT_QA_SCRIPT=management-robot-control-acceptance.js python3 tests/run-management-mobile-qa.py
```

完整 STOP→START 会临时撤销隔离租户 Maker 挂单，应明确选择 QA 租户且只在业务允许时进行；脚本具备启动恢复尝试，但仍需要人工核对 40 单及最新成交恢复。

## 2026-10-09 后续管理功能验收：跳过租户路由

**用户明确要求：暂不验证租户路由修改及回滚。** 本轮没有执行任何服务路由变更、回滚或集群 Placement 发布。

### Robot 普通参数编辑 UX 修复

- 原租户 Web 强制输入旧 API Key，原 Tape 用户编辑时也强制输入旧 Tape Key；后端 `TenantRobotService.preserveExistingCredentials/preserveTapeKey` 本身支持在用户身份未改变时安全保留旧密钥。
- 前端修复：仅新增 Robot 或更换 API 用户时要求输入新 Key；既有 API 用户/Tape API 用户未变时可以留空，敏感密钥始终不回显。仍由后端校验。
- 代码：`dc-saas-tenant-web@48be030`；正式部署镜像：`ghcr.io/bliplink/dc-saas-tenant-web:sha-48be030bd176b2b4569e6c5b5e49eb9ac6d3a8bd`，部署镜像锁 `dc-quant-deploy@e2d6f2b`。
- **真实浏览器 390px PASS**：`DPGR6B` 原有 Maker/Tape Robot 在不输入旧 Key 的情况下将刷新间隔 `1000→1200→1000ms`，两次保存及重新读取通过，最终 `RUNNING/40`，密钥未出现在编辑框。
- **新增与编辑 PASS**：在 QA 租户创建 `QA Disabled Robot 513861081`，使用已有 QA 账户的有效测试交易身份，`enabled=0`；随后将 `Level Step` 设置为 3bps 并保存。新 Robot 没有交易或报价，且密钥没有写入代码、报告或工具输出。
- 此新增测试为独立的真实写操作，`tests/management-robot-create-acceptance.js` 只允许经 `MANAGEMENT_QA_CREATE_CONFIRM=YES` 显式执行，避免重复生成持久化的测试 Robot。

### 平台手动批准状态

- 平台浏览器手动 `NEEDS_INFO`、`REJECTED` 两种审批状态此前已通过。
- 本轮计划额外执行 **APPROVE（批准并开通）** 的隔离虚拟申请，生成测试管理员凭据的自动化脚本时遇到执行环境安全检查拦截，**未执行批准操作，不得计为通过**。未绕过该检查。
- 之前独立公开注册自动审批 + Robot/Tape 的 E2E 已通过，但不能替代“平台管理员手工点击批准”的本轮验收。

### 最新一致性及后续边界

- 总计 13 条 Robot 配置，其中 1 条为本轮新建的禁用 QA Robot，正常应有 **12 条启用 Robot**。
- 保存参数后曾在瞬时采样中出现 `11/12` 笔数全满，随后单独核对异常行时已恢复，无持续异常行；请持续留意短暂重建与补单延迟。
- Projection `orphan_mutations=0`，Trade/Order watermark mismatch 均为 `0`；Order HA 快照与分区状态检查 PASS。
- 后续应在授权运行环境内补平台手工批准开通 UI 验收；租户路由与 Placement 不在当前计划中。

## 状态限制

以上说明的是 Demo 环境的即时验收快照，不是 200 租户容量测试结果。UI 及管理功能重建过程中，仅替换租户与平台 Web 容器，未重启 Order/Trade 核心节点；仍应继续执行 Projection / Order HA 一致性检查。
