# T394｜T393 Trade Web 正式镜像部署与 iPhone 13 回归（2026-11-01）

## 正式部署结果
- 已通过本地 WebCodex 原生命令实际停止并备份原 `dc-saas-trade-web` 容器，备份名：`dc-saas-trade-web-t393-backup`，未删除旧镜像。
- 新建正式容器 `dc-saas-trade-web`，运行镜像 `local/otc-t393-web:md-recent-consistency-final`，host network，`WEB_LISTEN_PORT=18088`，restart unless-stopped。
- 端口 18088 `/healthz` 返回 `ok`；镜像 Docker 状态 `running healthy`。
- 公网 `https://trade.opentradingcore.com/` HTTP/2 200，Cloudflare `cf-cache-status: DYNAMIC`，页面 JS 已是 `main_2026_11_01_15_52_08.js`。
- 原 Order/Trade A/B、Robot 服务保持运行；没有对 Order/Trade 注入故障或替换业务镜像。

## 本轮验收结果
- 最终源代码补齐超过 200 条历史成交保留最近认证执行的逻辑，Mocha 13/13 PASS，Webpack production build PASS。
- 正式端口 18088 的 Playwright Chrome iPhone 13 390x844 测试 6/6 组采样：MD 顶部价格、盘口中间价、最近成交第一条全部为 `77870.7`，200 行最近成交、时间列宽 67px、时间可见（显示 `~HH:mm:ss`）。
- 公网首次模拟测试曾复现一例短暂错位（MD/盘口 77964.3，最近成交第一条 77870.7），因此继续追踪而没有提前宣布动态稳定性。
- 已解码真实 MD WebSocket 压缩行情帧：`dc.md.trade.BTCUSDT.NWQYBB`，包含 200 条 `NoMDEntries`，最近一条成交价与 `LastPrice` 相等，并携带执行 ID；但 `MDEntryTime` 缺失。
- 公网随后 18 次、约 20 秒的连续采样覆盖 3 个不同顶部成交价：只有页面初始化时顶部价格为 `--`（最近成交已经加载），其余顶部价与最近成交首价一致，时间列持续可见。

## 剩余边界
- `~` 代表浏览器接收时间而非成交执行时间。需追查 Order/Trade→MD 的 `TransactTime/MDEntryTime` 丢失，恢复真实权威时间，才能移除近似标志。
- Playwright 是 Chrome 的 iPhone 13 模拟；Mac 上的 Playwright WebKit 浏览器二进制缺失，尚未完成真实 iPhone Safari 验收。
- 本轮没有执行长时稳定性压测、全量真实业务 Order/Trade HA SIGKILL 或资金/持仓一致性验收。
- 旧版 T393 文档中写的“尚未部署正式页面”被本 T394 证据更新为“已部署”，以本记录为最新状态。
