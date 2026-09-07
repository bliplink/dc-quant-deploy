# Web 三类角色、会话隔离与交易弹框生产验收（2026-09-07）

## 1. 发布结果

- 环境：独立 SaaS 生产验证栈 `18.140.45.126`，不影响同机量化系统。
- Web 源码：`dc-trade-web/saas-crypto@198e3ee208cfda21763ebf8b154512eb25995e2e`。
- 部署与验收：`dc-quant-deploy/saas-crypto@411179a`。
- 生产镜像：`ghcr.io/bliplink/dc-saas-trade-web:saas-crypto`。
- 生产镜像摘要：`sha256:af37da8a920dbb57f079c76416da58e80c2d9729952f8edb69f71cc797a605b9`。
- 容器状态：`dc-saas-trade-web` 为 `running/healthy`，`RestartCount=0`，`OOMKilled=false`。

## 2. 三类独立入口

通过桌面 SSH 转发访问 `http://127.0.0.1:18088` 时：

1. 交易页面：`/#/trade?location=WEB_E2E`。必须由 URL 携带 location；未登录可浏览行情、K 线、盘口和最近成交，交易时再登录或注册。
2. 租户服务中心：`/#/tenant`。新租户进入 `/#/apply`，已有租户进入 `/#/tenant-login`；登录表单输入 location、租户管理员用户名和密码，管理页面 URL 为 `/#/tenant-admin`，不在 URL 暴露 location。
3. 平台运营入口：`/#/platform-login`，登录后进入 `/#/platform-admin`。平台运营账号不开放公共注册，由运维安全配置。

直接打开 `/#/trade` 而不携带 location 时，页面会跳转到 `/#/tenant`，不会复用以前访问过的租户 location。

## 3. 会话与登出边界

- 交易用户使用 WebSocket 登录及交易会话存储。
- 租户管理员和平台管理员使用独立的 console token/session key。
- 租户或平台登录不会覆盖交易用户会话，三类角色不能复用对方身份。
- 交易页面登录后显示“退出登录”；退出通过 GW/LoginSvr 注销服务端 token，清除本地会话后回到同一 location 的公共交易页面。
- 租户管理员和平台管理员均有独立退出登录，退出只清理本角色会话并返回对应登录页。

## 4. 交易弹框改进

- 全仓/逐仓、杠杆与持仓模式弹框增加当前配置摘要、杠杆数字输入、滑杆、常用倍数快捷项和权威风险限额展示。
- 入金/出金弹框使用统一暗色专业主题，增加金额校验、USDT 单位、快捷金额/比例、可用余额、明确的确认与取消操作。
- 移除了会全局覆盖 Ant Design Modal 尺寸的旧样式，避免弹框被固定成狭小区域。
- 弹框适配窄屏，交易工作台移动端保持单模块切换与触控可达。

## 5. 生产自动化结果

| 验收项 | 结果 |
|---|---|
| 前端 K 线工具单测 4 项 | PASS |
| 盘口工具单测 3 项 | PASS |
| 完整 Webpack 编译（3233 modules） | PASS |
| 租户后端生命周期、数据库与双租户隔离 | PASS |
| 租户服务入口、平台后台、租户后台及各自登出 | PASS |
| 交易 WebSocket 登录、刷新恢复、断线恢复、token 轮换与登出撤销 | PASS |
| 公共态 MDSvr 行情、10+10 盘口、329 根历史 K 线与实时 K 线 | PASS |
| 桌面交易工作台、拖拽缩放、双语、杠杆和入金弹框 | PASS |
| 390×844 移动端、触控下单、无横向溢出与移动端登出 | PASS |

生产截图位于：

- `/data/dc-saas-runtime/e2e-artifacts/trade-config-dialog-en.png`
- `/data/dc-saas-runtime/e2e-artifacts/funding-dialog-en.png`
- `/data/dc-saas-runtime/e2e-artifacts/websocket-session-logout.png`
- `/data/dc-saas-runtime/e2e-artifacts/web-public-market.png`
- `/data/dc-saas-runtime/e2e-artifacts/workspace-mobile-en.png`
- `/data/dc-saas-runtime/e2e-artifacts/tenant-0907090454/`

## 6. bliplink 强平价核对

`WEB_E2E/bliplink` 当前 BTCUSDT 持仓为全仓 1 倍多仓，数量 `0.1 BTC`，开仓均价 `81219.357`，持仓保证金约 `8121.9357 USDT`，账户余额约 `11011.9563 USDT`。

数据库 `long_liq_price=0`，TradeSvr 发布报文持续为 `RiskValid=true`、`RiskStatus=VALID`、`LongLiqPrice=0`。由于账户权益足以使计算得到的强平边界小于等于 0，系统不存在正数强平价；Web 按约定继续显示 `--`。这不是强平计算遗漏或发布丢失。
