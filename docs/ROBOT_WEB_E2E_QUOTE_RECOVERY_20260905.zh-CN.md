# WEB_E2E Robot 盘口停止事件与恢复验收

## 结论

2026-09-05 生产环境 `WEB_E2E` 出现“Robot 状态显示 RUNNING，但 Web 盘口不再变化”。问题已经修复并发布。修复后 Robot、混合交易任务和真实浏览器盘口通过连续稳定性与服务重启恢复验证。

生产 RobotSvr 当前固定镜像：

`ghcr.io/bliplink/robotsvr:sha-7f81def63cab01a7bc335b6d6829de47da522fca`

## 根因

现场同时存在两个相互叠加的问题：

1. RobotSvr JVM 和配置轮询线程仍存活，但 100ms 报价定时任务已经从 `ScheduledThreadPoolExecutor` 队列消失。Java 固定延时任务一旦有未捕获的 `Throwable` 逃逸，后续执行会被永久抑制；容器仍为 running，旧的 `RUNNING/40` 心跳也会造成假健康。旧进程未初始化 Robot 专属日志，原始异常已被执行器吞掉，无法事后还原具体 Throwable。
2. 常驻压测脚本只刷新普通模拟交易用户的会话，没有刷新用于查询 Robot 活动委托的账号会话。会话过期后脚本把认证失败误报为 `0/0` 盘口；GW 暂时不可用时，重新登录失败还会让压测进程退出。

## 修复

- RobotSvr 为配置轮询和报价循环统一增加异常边界。除内存耗尽外，异常会记录完整堆栈并在下一周期重试，不再静默终止定时任务。
- 内存耗尽时主动终止 JVM，由 Docker `unless-stopped` 策略重新拉起，避免进程假活。
- RobotSvr 启动时加载 `log4j.ini`，日志写入 `RobotSvr.log`，并保留标准输出。
- 增加调度恢复单元测试，模拟 `AssertionError` 逃逸后验证固定延时任务仍会再次执行。
- 常驻压测为 Robot 查询账号增加主动和被动会话刷新；GW 不可用期间登录失败只记录并重试，不再终止常驻任务。

对应 Git 提交：

- RobotSvr `7f81def`：`fix(robot): keep quote scheduler alive after errors`
- dc-quant-deploy `1095465`：`fix(test): refresh robot soak query session`
- dc-quant-deploy `5fe6b03`：`fix(test): survive gateway outages during robot soak`

## 验收结果

### 单元测试

RobotSvr 共 44 个测试通过，0 失败、0 错误。新增测试明确验证一次未捕获 Error 不会使后续报价周期消失。

### 生产恢复测试

- 保持 RobotSvr 原进程不重启，重启 OrderSvr。
- Robot 从 `DEGRADED/0` 自动恢复到 `RUNNING/40`，恢复约 64 秒。
- Web 恢复严格 10 个买档和 10 个卖档。
- 重启 GW 时日志捕获到 `Connection refused`，新异常边界明确输出“scheduled loop will retry”；随后配置轮询、API 会话、TCP 行情订阅和报价均自行恢复。
- 常驻混合交易进程在 GW 中断期间保持原 PID，恢复后继续下单。

### 故障后 3 分钟干净窗口

- 后台盘口样本：137。
- Robot 最小活动深度：买 20 档、卖 20 档。
- 混合请求新增：548。
- 拒绝增量：0。
- 后台缺档增量：0。
- 真实 Chromium 累计采样：1,700。
- Web 最小/最大可见深度：买 10/10、卖 10/10。
- Web 缺档：0；页面错误：0。
- RobotSvr 启动时间和 RestartCount 未变化，证明恢复不是人工重启 Robot 得到的。

## 证据

生产服务器证据目录：

`/data/dc-saas-backups/release-20260904T080903Z/test-results/`

- `robot-web-e2e-stable-after-fix-20260905T132446Z.log`：3 分钟干净窗口完整断言和 PASS。
- `robot-web-e2e-after-fix-20260905T132832Z.png`：修复后 WEB_E2E 生产交易页，盘口为 10+10。
- `robot-ordersvr-gw-recovery-20260905T131501Z.log`：OrderSvr 恢复时间线，以及首次 GW Web 等待超时的诊断记录。
- `robot-gateway-recovery-final-20260905T132021Z.log`：GW 故障注入期间常驻压测原 PID 存活、活动单恢复和接受计数继续增长的时间线；新页面的 WebSocket snapshot 晚于该脚本的 90 秒等待窗口，随后由真实浏览器和干净窗口确认恢复。

## 当前运行状态

Robot 按 APSSvr 的 Binance ticker 继续为 `WEB_E2E/BTCUSDT` 维护 20+20 个后台活动价位；MDSvr 向 Web 发布该 location 的独立行情，页面展示前 10+10 档。常驻任务继续混合执行点价、IOC、盘口内挂单和撤单，用于长期观察。
