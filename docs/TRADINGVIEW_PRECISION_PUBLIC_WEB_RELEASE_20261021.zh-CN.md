# 2026-10-21｜交易图表精度、订阅去重与主站 UX 发布

## 镜像与配置

| Web | 发布镜像 | Compose 版本文件 | 部署源码 |
| --- | --- | --- | --- |
| 交易终端 | `local/dc-saas-trade-web:precision-and-chart-subscriptions-20261021` | `config/trade-web-chart-precision-20261021.yaml` | `bliplink/dc-trade-web` 分支 `codex/production-trade-ux-20261020`，提交 `5a0b03b` |
| 主站 | `local/dc-saas-public-web:customer-site-i18n-20261021` | `config/public-site-review-20261021.yaml` | `bliplink/opentradingcore-web` 分支 `codex/homepage-i18n-production-review-20261021`，提交 `9e783a3` |

仅重建 `web`、`public-web` 两个静态 Web 容器，Order、Trade、MD、Common 均未更新或故障注入。GitHub CI 没有使用，均在 Mac 本地构建；各源码提交均带 `[skip ci]`。

## 验收证据

1. 主站：Playwright 1440、768、390px；全部加载 42 个租户目录，搜索、分页、中文租户产品「2 个」、手机「语言」、Demo 动态第一个租户 URL `GAAKY8`、中文 API `/zh/`、无 JS 异常和整页溢出。已部署主站健康检查 `healthy`。
2. 交易图表：`GAAKY8 / QAA911F381USDT` 的 tick_size `0.10000000`、price_precision `1`。TradingView minmov 不再固定 0.1，而是正确的 `minmov=1, pricescale=10`；图表 OHLC 按对应精度显示。JS 单测新增 9 条，加此前 23 条回归，32 条通过；生产构建通过。
3. 正常行情就绪后，真实 Playwright 从 BTCUSDT → QAA911F381USDT → BTCUSDT → QAA911F381USDT，图表 iframe 不重建、活跃行情订阅数始终为一且与选中产品一致，JS 错误 0；去掉重复 fitLatestRange 引起的额外历史 K 线 RPC，并在切换离开产品后停止无用的历史重试。
4. 隔离版和生产版均经过检查，两个容器已替换并通过本机服务健康检查。

## 不得宣称全套生产验收通过

- **冷启动快速切换**：如果首个 K 线实时订阅还未创建就切换到另一产品，又切回，TradingView 可能沿用图表缓存但未绑定前一产品的实时回调。现有单次 resetData 不能保证全部此类时序恢复。未通过全量弱网/高频图表切换 QA；后续需完善图表初始化/状态机。
- K 线切换到不同产品或不同周期时，按需请求这个市场/周期的历史数据是正确行为。已删除的是不必要的重复全量加载。
- Trade/Robot：此前发现 Trade strict commit `no live current-epoch physical replica`，对应 `queryTradePosition: PARTITION_NOT_READY` 和机器人降级；此 HA/数据一致性问题必须等待 Common/Trade 统一更新并通过真实恢复验证，不能因本次前端通过而放行生产交易。
