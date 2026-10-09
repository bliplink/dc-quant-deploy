# DUJE16 Robot DEGRADED 根因与未完成恢复记录（2026-10-10）

## 当前状态：仍需单租户安全恢复
> **重要更新：** 已通过平台合法会话实测 `OrderSvr/queryOpenOrder` 被 `P246 PARTITION_NOT_READY` 拒绝；确认 OrderSvr A 反复发生 `replica catch-up GAP`。在完成 Order HA 权威一致性修复前，**禁止执行以下所述 Robot STOP/START/RESTART**。参见 [P246 HA 恢复事故调查](ORDER_P246_CATCHUP_GAP_DUJE16_INCIDENT_20261010.zh-CN.md)。


- Mac mini MySQL `dc.dc_tenant`：**13 租户，均 TRIAL**；`dc.dc_tenant_robot`：**14 个 Robot 配置**（13 个 enabled=1，另有 1 个 `DPGR6B` 禁用的 QA Robot）。
- 启用的 13 个中 **12 RUNNING，1 DEGRADED**，异常项为 `DUJE16 / trial-liquidity-BTCUSDT`，`open_order_count=0`；原始错误 `RUNTIME_FAILURE`、`gateway TCP response is empty for cancelBatchOrder`，`update_time=2026-10-09 09:40:35.844`。最新 `last_heartbeat_time` 持续刷新至 2026-10-10 06:25（本机 +08），`runtime_owner=colima`、运行租约正常续租。这意味着租约与进程存活**不等于**对该租户已经恢复 40 单。
- ClickHouse `dc.market_trade` 对该租户最近 300 秒 **0 条**，最近一条历史记录距采样约 4,500–4,800 秒。与正常租户 `DPGR6B` 最近 300 秒约 48 条形成鲜明对比。
- `MDSvr/queryPublicMarket` 读接口返回 `code=0`、BTCUSDT **10 买档+10 卖档**；单租户 Playwright `market-readonly-tenant-survey.js` 的 UI 也能显示买卖盘、200 条历史成交，`PASS`。**这不是 `DUJE16` 自己的 Robot 正常报价/新成交证据。** 需要以 Robot 自有活动单 + 权威成交记录验证恢复，避免只看 MDSvr 缓存快照。
- RobotSvr 持续运行，0 次重启，无 OOM，旧线上镜像 `ghcr.io/bliplink/robotsvr:sha-abd7efa1ffa7921f8c384f92c09f25c46419f63b`。其余 12 个正在报价，不应为一条异常直接重启整个 RobotSvr。

## 从源码定位的错误上报缺陷

`RobotWorker.runOnce()` 达到故障阈值时，会调用 `cancelOrders(instanceOrderPrefix)` 做安全清理。原实现把**撤单和失败状态心跳**放在同一个 `try` 中。如果 `cancelBatchOrder` 出现空 TCP 响应等异常，直接进入 `catch (Exception ignored) {}`，**连当前 ERROR/DEGRADED 心跳都可能无法正确上报**。这可能让 `runtime_status` 与 `last_error_message` 显示先前陈旧状态，而不是最新失败原因。

RobotSvr `saas-crypto` 提交 [`5941ee6`](https://github.com/bliplink/com.app.dc.robotsvr/commit/5941ee6032f607a6bccc2b8da305e57f91198ad0) 修复：

- 即使安全清理失败，也尽可能独立上报 `RUNTIME_FAILURE`，故障超过阈值时保留 `ERROR` 状态；**不把网关撤单超时当作已成功撤单**，不将失败的 Robot 标记 RUNNING。
- 错误详情保留原始失败和“quote cleanup unconfirmed”警示，掩码秘密，并将信息限制为 900 字符；ManagerSvr 心跳上报本身失败时写入**限频**告警，不在日志中输出凭据。
- 新增 `RobotRuntimeFailureStatusTest` 3 条离线单元测试，GitHub Actions `37998813915` 的 Maven/ARM64+AMD64 镜像构建 **SUCCESS**。
- **此代码尚未替换线上 RobotSvr，不等于 DUJE16 已恢复。** 正式线上更新前，应检查业务路由、现有 12 户的报价连续性及安全清理/回滚计划；本轮不擅自重启。

## 多租户压力测试准入门禁加固

`tests/check-tenant-ramp-readiness.py` 新增**只读** MySQL `SELECT` 查询 `enabled=1` 的 Robot 状态、实际 `open_order_count` 与心跳年龄。查询在 MySQL 容器内使用已有环境变量提供密码，**不把密码值展开到宿主命令行**。任何启用的 Robot 未 RUNNING、挂单为零或心跳超过 45 秒会使门禁返回 `NOT_READY`。凭据查询失败则直接 `TELEMETRY_UNAVAILABLE` fail-closed。

本轮实际门禁（UTC 2026-10-09 22:25:03）：

- `gate=NOT_READY`、`ENABLED_ROBOTS_UNHEALTHY:1/13`；
- `DUJE16` 实时状态 `DEGRADED`、`openOrders=0`、`heartbeatAgeSeconds=0`；
- CPU PSI `avg10=48.94%`、RobotSvr 占自身 1.25 核配额约 `104.74%`；
- 最近 300 秒 ClickHouse `market_trade=600` 行，仅表明行情入库、**不是成交撮合 TPS**；
- OrderSvr B 老年代仅占最大容量约 `9.87%`，该采样 3 秒内 Full GC `0`。

## 下一步单租户恢复的安全前提

1. 对 `DUJE16` 的 `OrderSvr/queryOpenOrder` 使用授权会话只读核对实际、未结订单；**不能只用 ManagerSvr 的 `open_order_count=0` 判断撤单已经生效**。必要时核对残留订单的身份、分区和订单前缀。
2. 在授权的租户管理流程中针对 **仅 `DUJE16`** 做一轮 STOP/START 或等效的 Robot 重建；先完成残单/资金/持仓安全检查，确认路由故障已消失。不得直接 `UPDATE dc_tenant_robot SET runtime_status='RUNNING'` 伪造恢复，也不允许跨租户或重启整个 Robot 容器。
3. 仅在 40 单/10+10 买卖报价、当前 5 分钟新增真实市场成交、持续心跳和稳定 Order/Trade 状态均通过时，标记单租户恢复完成。其余 12 户也要持续观察。
4. 即使此租户恢复，全局仍有 CPU PSI/Robot CPU 配额压力和 Order HA 长稳验收未关闭，不能宣布 200 租户负载准入通过。

**本轮没有创建租户、下单、重启服务、修改持仓/余额、编辑运行中 Robot 参数或更新生产数据库状态。**
