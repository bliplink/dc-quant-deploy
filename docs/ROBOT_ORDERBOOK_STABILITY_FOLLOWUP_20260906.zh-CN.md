# WEB_E2E Robot 盘口稳定性补充验收（2026-09-06）

## 本次新增发现

在首次恢复 Robot 后，后端 `queryOpenOrder` 长期出现 20 买、21 卖。进一步核对发现：

1. 盘口中存在长时间未完成清理的 `Partially_Filled` Demo 报价残单。
2. 常驻压测脚本为了查询 Robot 自有委托，使用 Robot 交易用户建立 Web 会话。
3. LoginSvr 当前会在同一用户再次登录时轮换旧会话，因此该监控操作会让 RobotSvr 的 API 会话失效，周期性触发重认证与盘口恢复窗口。
4. OrderSvr 重载清除了不落库的 Demo 残单，Robot 随后恢复为严格 40 张活动报价单。

监控脚本已改为通过 GW 调用 MDSvr 的 `queryPublicMarket`，直接检查租户 Web 实际可见的 10 档买卖盘，不再登录 Robot 用户；Robot 自身的活动单总数继续通过 `dc_tenant_robot.open_order_count=40` 校验。

部署提交：`1928f938ad37e46b6c1ec4af53857e7453f864d1`

## WebSocket 短暂缺档

隔离会话干扰后，MDSvr HTTP 公开快照持续保持 10 买 + 10 卖，但 Chromium 250ms 高频采样曾捕获 2 次买盘仅剩 2 档。说明 OrderSvr 已接受新报价不等于 MDSvr/GW/Web 已看到新档位，原 750ms 的新旧报价桥接窗口不足。

RobotSvr 已把新单接受后、旧单撤销前的行情传播保护窗口延长到 2 秒。它不会改变报价档数、资金预算、杠杆、最大持仓和对冲规则，只让旧报价多保留一小段时间，等新报价经过 OrderSvr、MDSvr、GW 到达浏览器后再撤销。

RobotSvr 提交：`4d0572b262af916e0deb37f1ff21649ed49bf59e`  
生产镜像：`ghcr.io/bliplink/robotsvr:sha-4d0572b262af916e0deb37f1ff21649ed49bf59e`

## 发布后验收

- RobotSvr：`running`，容器重启次数 0。
- Robot 运行状态：`RUNNING`。
- Robot 活动报价：40 张。
- MDSvr 租户公开盘口：10 买 + 10 卖。
- Chromium 高频采样：776 次，最小/最大买盘均为 10，最小/最大卖盘均为 10。
- 混合下单：596 笔已接受，0 笔拒绝。
- 后台盘口缺口：0。
- 浏览器盘口缺口：0。
- 页面错误：0。
- 监控引起的 Robot 会话刷新：0。

最终观察器输出：

```text
HEALTHY robot=RUNNING/40 active=10+10 persisted=0 web=10-10+10-10 accepted=596 rejected=0 auth_refresh_delta=0
```

常驻压测和浏览器监控继续运行。以上是发布后的短窗口验收；长期稳定性仍以小时汇总和后续持续观测结果为准。
