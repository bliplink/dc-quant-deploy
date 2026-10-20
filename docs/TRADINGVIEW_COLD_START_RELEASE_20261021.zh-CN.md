# 2026-10-21｜TradingView 冷启动快速切换修复交付

- 源代码：`bliplink/dc-trade-web` 分支 `codex/production-trade-ux-20261020`，提交 `974fc61`，`[skip ci]`。
- 镜像：`local/dc-saas-trade-web:kline-coldstart-ready-20261021`。覆写文件：`config/trade-web-kline-coldstart-20261021.yaml`。仅使用 `docker compose ... up -d --no-deps --force-recreate web` 更新交易 Web，保持 Order/Trade/MD/Common 未重启。
- 修复：避免首个 TradingView 图表启动、尚未产生 `subscribeBars` 实时回调时，先切到自定义产品再切回 BTCUSDT 导致实时订阅永久丢失。保存迟到 callback，但不向非当前市场订阅；返回原产品时恢复它的唯一有效 K 线订阅，不重新加载整个交易页。
- 测试：隔离部署 7 个新 Chrome 上下文冷启动快切 7/7 PASS。发布到 Demo 后，同一脚本再跑 4/4 PASS。`BTCUSDT 5M → 1M → 5M → 15M → 5M` 周期切换，活跃 topic 始终为一个、TradingView iframe 没有重建、浏览器导航与账户 RPC 计数不增加、网关 WS 连接数不增加、JS 错误 0。浏览器端 `qa/tradingview-coldstart-fast-toggle.cjs`、`qa/tradingview-period-data-qa.cjs`，程序单测 16 PASS，生产编译 PASS。
- ClickHouse 只读核验：`GAAKY8/QAA911F381USDT` 无 `market_trade` 和 `kline` 记录；当前自定义产品图表显示无成交历史是正确结果。`GAAKY8/BTCUSDT` 有成交及 5M 历史。不得用标记价格数据充当真实成交蜡烛。
- 正式开放仍受 Trade 集群严格副本 READY、Robot DEGRADE/ERROR 以及完整交易一致性/200 租户压测等未完成事项限制。本轮不作整体生产 HA 验收结论。
