# Trade Web 首屏 K 线/盘口显示时序专项优化与验收（2026-10-09）

## 用户可见的问题

多个已有 SaaS 租户的交易页打开时，5M K 线、双边盘口、最近成交展示顺序不一致；有些租户 K 线先展示、盘口长时间空白，让页面看起来很卡。这不是可以用一个统一遮罩掩盖的问题，必须测量各链路真实准备时间。

## 实际 Chromium 首屏计时基线（修改前 Trade Web @030df71）

同一测试运行，1366×900 无登录的租户交易页，带原有实时订阅；计时从 `page.goto` 前开始直到页面首次获得有数据的 K 线历史与 10 买/10 卖的完整盘口（毫秒）：

| location | Chart bars | 10 bid + 10 ask | gap |
|---|---:|---:|---:|
| DPGR6B | 2362 | 9164 | 6802 |
| QS12O4 | 2591 | 2085 | 506 |
| BIHZYE | 2589 | 1836 | 753 |
| UJ2WZD | 1980 | 2233 | 253 |
| T6X2PT | 2454 | 1941 | 513 |

`DPGR6B` 的单次首帧差达 6.8 秒，故客户感知问题成立。此样本不足以推断 5 个租户的性能分布或 p95/p99，也不是订单 TPS。完整 JSON 在 E2E 容器 `/artifacts/first-paint-20261009-UX/first-paint.json`。

## 第一阶段修复：压缩不必要等待+让进度可见

`dc-trade-web@952614fb12131ea97b22bceecc6e3588198ca55b`（`saas-crypto`）：

1. `Header.scheduleOrderBookBootstrap`：现有主链路仍优先 WebSocket。完整盘口超过 **3.2 秒**仍没有时最多发起一次当前租户限定的 `MDSvr.queryPublicMarket` 读取，代替以前的 **8 秒**延迟。请求使用原有业务分区键，收到后仍检查当前租户、品种、WebSocket 数据是否已更新；**不是轮询、不改路由、不写交易数据**。
2. TradingView `CusDataFeed.resolveSymbol` 的固定 1 秒异步定时延迟改为 0 毫秒异步回调，让 5M K 线历史请求更早启动，不修改默认 5M。
3. K 线历史状态暴露 `symbol`、`location`、`resolution`，交易页面只把当前租户/品种的 K 线计为就绪，防止切换品种时误用旧状态。
4. Trade UI 在行情头下增加一条轻量、双语的**加载阶段状态行**。分别显示 Chart / Order Book 的连接中、已就绪，超过 8 秒显示等待数据/报价。实际行情和交易按钮不被遮罩，不强行阻塞已加载的图表。两块状态每 500ms 最多仅在变化时更新，全部就绪后停止检查，切换品种重置。
5. 全部改动仅在 Trade Web，保持 MDSvr、OrderSvr、TradeSvr、RobotSvr、MySQL、ClickHouse、当前租户路由与 Placement 不变。

## 验收与未结束的风险

量化测试脚本为 `tests/trade-first-paint-timing-e2e.js`（`E2E_TENANTS` 可选择租户），记录 `chartFrameMs`、`chartBarsMs`、`bookFullMs`、`priceMs`、新页面的 `marketReadyMs`；同时检查浏览器 JS 异常。部署后应使用相同租户、分辨率、测试窗口重复运行，记录相对基线的变化，不应声称所有租户无异常。

```bash
docker cp tests/trade-first-paint-timing-e2e.js \
  dc-saas-web-e2e-runner:/runner/trade-first-paint-timing-e2e.js
docker exec -e E2E_ARTIFACT_DIR=/artifacts/first-paint-post-ux-fix \
  dc-saas-web-e2e-runner bash -lc \
  'NODE_PATH=/runner/node_modules node /runner/trade-first-paint-timing-e2e.js'
# 常规 12 租户抽查继续用 tests/market-readonly-tenant-survey.js
```

需要继续核查：K 线历史偶尔无数据的独立根因，WebSocket 订阅延迟与首帧丢失，Robot CPU/Colima CPU PSI 高（此前某次 CPU some avg10=55.88%）。如果上线后首帧差仍频繁超过 3~5 秒，进一步调查 MDSvr Topic snapshot 路由与 Gateway 订阅 ACK，而不能只增加客户端超时或隐藏空盘口。

本阶段未修改租户路由或回滚；不会因改变交易 Web 展示逻辑就宣称撮合容量、HA 或 Tape 权威成交一致性已验证。
