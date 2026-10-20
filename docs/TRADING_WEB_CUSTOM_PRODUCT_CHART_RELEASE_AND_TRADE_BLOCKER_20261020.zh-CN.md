# 2026-10-20｜交易 Web 自定义市场交付及 Trade/Robot 生产阻断

## Web 用户交付版

- 源码：`bliplink/dc-trade-web` 分支 `codex/production-trade-ux-20261020`，提交 `70ef18c`（`[skip ci]`，没有触发 GitHub Actions）。
- Demo 镜像：`local/dc-saas-trade-web:market-icon-chart-switch-20261020`（image ID `sha256:021853b153c6d933b13be5263189eb31c47562e19d730f6295cdc8439356ff5e`），部署配置：`config/trade-web-market-icon-chart-switch-20261020.yaml`。仅重新创建 Web 容器；Order、Trade、MD、Common 未替换。
- 改动：去除匿名下单说明性文字；持仓登录/注册按钮 PC 和移动端统一；自定义品种默认币种图标；K 线切换期间不显示旧市场蜡烛，TradingView 处理完成后再显示当前品种；K 线状态按 `symbol + location + resolution` 隔离。
- 验证：独立测试租户 `MVH51T/BTC003USDT`、`GAAKY8/QAA911F381USDT` 的真实 Playwright 已在**部署后的容器**通过：自定义图标 naturalWidth=40、K线选中品种和图表内部一致、切换遮罩自动清除、JS 异常为零；`QAA911F381USDT → BTCUSDT → QAA911F381USDT` 连续切换通过；PC 登录/注册按钮均为 96x34 px，手机端 390x844 亦一致；1280x720、1366x768、1440x900、1920x1080、390x844 视口均通过。
- 当前无 K 线的自定义市场要显示真实空数据，不得借用 BTCUSDT K 线。`QAA911F381USDT` 查询在本轮曾返回零根有效 K 线，仍需持续成交、历史和实时 K 线业务验证。

## 未完成：生产级 Trade HA/Robot 阻断

- 恢复 `dc-saas-robotsvr` 原停机的旧容器（此前退出码 137，且 `OOMKilled=false`），没有改变其镜像或机器人业务代码；新租户 `GAAKY8` 初始化任务已 `DONE/COMPLETE` 且产品 BTCUSDT 有 40 笔活动委托。
- 机器人运行状态波动，取样从约 37 RUNNING 下降至 21 RUNNING、10 DEGRADED、6 ERROR、6 WAITING_MARKET_DATA；此为单次运行快照而非稳态测试通过结论。
- 故障证据：16 个机器人报 `RUNTIME_FAILURE`，错误包含 `gateway rejected queryTradePosition: PARTITION_NOT_READY service=TradeSvrA/B partition=Pxxx epoch=1`；TradeSvrA/B 日志反复显示 `Trade strict commit PAUSED: no live current-epoch physical replica partition=Pxxx`，如 P052、P210、P080、P079、P245 等。
- 这说明 Trade 业务分区没有达到本代物理副本就绪的严格提交条件。系统选择暂停而不是无保护写入是正确安全边界，**不得关闭严格复制、跳过持仓检查或伪造 Robot RUNNING**。Common/Trade 更新后必须完成物理副本恢复、READY、主切、追平、一致性及 50/200 租户负载验收。当前不符合完整生产对外开放门槛。
- 本轮仅完成 Web 产品界面交付及 Trade 障碍定位，不声称解决 Common/Trade 集群问题。
