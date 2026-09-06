# WEB_E2E Robot 盘口故障修复与生产验收（2026-09-06）

## 结论

`WEB_E2E/BTCUSDT` 盘口已恢复，RobotSvr、GW、MDSvr 和真实 Chromium 页面均已验证正常。

- Robot 后台持续维持 20 档买价和 20 档卖价。
- MDSvr/Web 按当前展示配置稳定显示 10 档买盘和 10 档卖盘。
- 真实浏览器 136 次连续采样无缺档、无页面错误。
- 混合下单任务继续运行，最终观测为 `accepted=1933`、`rejected=0`。

## 根因

本次故障由两个独立条件叠加造成：

1. Robot 控制面 API 会话过期后，ManagerSvr 返回 `authenticated robot runtime identity is required`。客户端原来只识别通用 session 错误和 tenant identity 错误，没有清除 PLATFORM 运行时会话并重新登录，导致配置轮询停止在失败重试状态。
2. 会话恢复后，测试做市账户净多仓达到 `max_position_qty=10`。Robot 的仓位风控正确地禁止继续挂买单，只保留卖单；原压测脚本又要求买卖两侧同时存在才继续成交，因此没有用户继续买入 Robot 卖盘来释放库存，形成单边盘口自锁。

第二项是测试流量闭环缺失，不应通过取消 Robot 的最大持仓保护来解决。

## 修复

### RobotSvr

提交：`c2911186c96d673851a4ff409de4d2dee4d8e9e1`

- 将 `authenticated ... identity` 统一识别为权威会话缺失。
- Robot 运行时请求失败后清除旧 session，以相同 PLATFORM API Key 重新登录一次并重试原请求。
- 增加 `authenticated robot runtime identity is required` 回归断言。

生产镜像：

`ghcr.io/bliplink/robotsvr:sha-c2911186c96d673851a4ff409de4d2dee4d8e9e1`

镜像摘要：

`sha256:ea2cd33408b3a0821d7dae81806e2200d6b5c0fa4e773267de50171926adab8c`

### 常驻混合交易任务

提交：`e9224c12b8eeda3edf7099447fda7df29f5256d1`

- 当后台活动盘口仅剩一侧时，选择不承担 tape 任务的独立测试用户。
- 先撤销该用户遗留的压测挂单，防止自成交保护取消恢复订单。
- 经 LoginSvr/GW/OrderSvr 正常链路提交小额 IOC，成交剩余 Robot 深度，使净仓重新进入最大持仓以内。
- 15 秒限频，并记录接受、拒绝及会话刷新；不直写订单、成交、资金或持仓数据。
- RobotSvr 的仓位限制和生产交易规则保持不变。

## 验收结果

### 1. 单元测试

RobotSvr：39 个测试通过，0 失败，0 错误。

### 2. 最大持仓故障注入

把测试 Robot 的 `max_position_qty` 临时从 10 降到 9.90：

- 注入前净多仓：9.9917 BTC。
- Robot 按风控移除买盘。
- 守护脚本检测到单边盘口，经 GW 提交 `Buy IOC`。
- 净多仓下降到 9.9447 BTC。
- 测试结束后上限自动恢复为 10，买卖双边恢复。

### 3. PLATFORM 会话失效注入

使用相同运行时 API Key 主动登录，使 Robot 旧会话失效：

- 注入登录返回 `code=0`，权威用户和 location 校验通过。
- LoginSvr 记录两次会话轮换：第一次注销 Robot 旧会话，第二次证明 Robot 自动重登并注销注入会话。
- 整个 24 秒窗口中 Robot 保持 `RUNNING`，心跳年龄为 0～2 秒。
- 19 个后台盘口样本最小值为 20 bid / 20 ask，缺档样本为 0。

### 4. Web 页面

重建浏览器监控后：

- Chromium 连续采样：136。
- 买盘最小/最大可见档数：10/10。
- 卖盘最小/最大可见档数：10/10。
- 缺档样本：0。
- 页面错误：0。
- 当前页面截图：`/data/dc-saas-runtime/robot-soak/web-market-live.png`。

最终观察器状态：

`HEALTHY robot=RUNNING/40 active=20+20 persisted=0 web=10-10+10-10 accepted=1933 rejected=0`

其中 `persisted=0` 符合 Robot 报价 `isdemo=true`、不落 MySQL 历史委托表的约定。报价替换期间后台偶尔短暂读到 40 档同侧价格，是先挂新单、后撤旧单的无断档桥接过程；MDSvr 对 Web 发布的可见深度仍稳定为每侧 10 档。

## 生产证据

证据目录：

`/data/dc-saas-backups/release-20260904T080903Z/test-results/`

- `robot-runtime-session-expiry-20260906T012146Z.log`：旧镜像运行时会话失效现场及临时恢复。
- `robot-soak-inventory-recovery-20260906T015153Z.log`：新守护脚本启动与基础深度。
- `robot-soak-inventory-forced-*.log`：最大持仓故障注入与自动减仓。
- `robotsvr-runtime-reauth-release-20260906T015401Z.log`：镜像发布、标签、摘要与环境备份。
- `robotsvr-runtime-session-injection-direct-20260906T020051Z.log`：PLATFORM 会话失效及自动重登验证。
- `robot-web-orderbook-final-20260906T020206Z.log`：最终 GW 深度和真实浏览器验收。

## 当前运行状态

生产 RobotSvr 已固定到 `c291118` 镜像，常驻混合交易和浏览器监控均在运行。最终人工观察器检查已从故障注入产生的历史告警恢复为 `HEALTHY`。
