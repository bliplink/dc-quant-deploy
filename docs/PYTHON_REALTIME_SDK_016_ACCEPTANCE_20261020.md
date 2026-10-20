# OpenTradingCore Python SDK 0.1.6 + Python-only API Docs 验收

日期：2026-10-20。该记录只涉及 Python SDK、文档和只读实时订阅验收，未修改 Common、Trade HA 或 Order HA 集群机制。

## 交付规则

- 外部 `https://api.opentradingcore.com/en/`、`/zh/` 只描述 Python SDK 的**方法、参数、返回值和示例**；不提供面向用户的原始 HTTP 调用表、WebSocket Topic 或报文结构。源码中的 transport 保留为 SDK 内部实现。
- Python SDK 源码仓库：`https://github.com/bliplink/opentradingcore-api-docs/tree/codex/python-realtime-methods-sdk-016-20261020`，提交 `3ad7bcc`。
- 0.1.6 安装包：`https://api.opentradingcore.com/sdk/opentradingcore-0.1.6-py3-none-any.whl`。
- 源码包：`https://api.opentradingcore.com/sdk/opentradingcore-python-sdk-0.1.6.zip`。
- Demo 镜像：`local/dc-saas-api-docs:python-only-016-20261020`，Compose 覆盖为 `config/api-docs-python-only-016-20261020.yaml`。旧 SDK 包（含 0.1.5）保留以确保向后兼容。
- 0.1.5 已发布，因此实际修复最近成交订阅映射采用 **新版本 0.1.6**，不修改原版本号下的代码。

## 公开市场 Python 方法

- `PublicMarketClient.products()`：当前租户启用产品。
- `PublicMarketClient.snapshot(symbol)`：当前租户、指定产品的公开盘口和成交快照。
- `PublicMarketClient.ticker_24h(symbol)`：交易核心表头同源指标：最新价、涨跌幅、标记价、指数价、高低价、资金费率和 UTC 8 小时倒计时、Premium、基础资产成交量、USDT 成交额。
- `OpenTradingCoreClient.kline(symbol, interval="5m", limit=200)`：K线查询，需登录。
- `MarketStreams.subscribe_ticker(symbol)`：独立的 MD 行情表头订阅（对应当前产品的聚合最新行情）。
- `MarketStreams.subscribe_order_book(symbol)`：盘口初始快照和增量订阅。
- `MarketStreams.subscribe_recent_trades(symbol)`：真正的公开最近逐笔成交（已更正，**不同于** ticker，旧版 0.1.5 误用了 ticker 主题）。
- `MarketStreams.subscribe_candles(symbol, interval="5m")`：K 线订阅。
- `MarketStreams.events()`：收到通知后逐条迭代；只交付主动订阅的主题，订阅错误返回异常。因无法保证所有消息都持续收到，断线后须重订阅并重建必要快照。
- `watch_ticker_24h(market, symbol, interval_seconds=15)`：**定时查询刷新**，而非伪造独立 WebSocket 推送。

### 24h 指标的现有 MD 口径

`ticker_24h` 主键由 `location + securityID` 双维度限定，绝不使用主站的全租户交易合计。

| 字段 | 意义 |
| --- | --- |
| `price_change_percent` | 相对 MD 已发布 `OpenPrice` / `ClosePrice` 参考价的涨跌幅 |
| `mark_price`, `index_price` | MD 的标记价格、指数价格 |
| `high_price_24h`, `low_price_24h` | MD `OhlcManager.getOhlc1D(location, securityID)` 高低价 |
| `funding_rate_percent`, `funding_countdown_utc` | MD `Fee` 换算百分数；UTC 固定 8 小时周期倒计时 |
| `premium_percent` | `(mark_price - index_price) / index_price × 100` |
| `volume_24h`, `turnover_24h_usdt` | MD 1D 聚合成交量和成交额 |

必须明确：当前服务是 **1D 聚合**，不能保证严格向前滚动 24 小时。新 Demo `N9NZV5/BTCUSDT` 在测试时能读取标记价/指数价/资金费率/Premium，但无成交样本时，高低价、成交量、涨跌幅返回 `None`（不是零，不使用虚构数字）。

## 私有账户 Python 方法

- `OpenTradingCoreClient.balances()` / `.positions()`：登录后的 Trade 资金余额和持仓；Order-only 产品无 TradeSvr 资金账本。
- `.order_history()`, `.open_orders()`, `.execution_history()`, `.funds_history()`：委托、当前订单、成交记录、资金流水查询。
- `AccountStreams.subscribe_balances()`, `.subscribe_positions()`, `.subscribe_order_status(symbol)`, `.subscribe_executions(symbol)`：登录交易员关联的订阅；分别要求 `ACCOUNT_READ` 或 `ORDER_READ`。
- `watch_funds_history(api, interval_seconds=15)`：资金流水定时只读刷新，**不是**私有资金流水实时推送。
- 租户/客户隔离按已认证的身份与服务端权限执行；不可通过 SDK 任意指定其他租户用户 ID。

## 验收证据与待验收项

**已通过：**

1. SDK v0.1.6 单测 **38/38**，包含鉴权与错误 ACK、跨租户消息排除、Ticker/最近成交不同订阅源、Python 3.9 对象导入、Funds 只读分页与产品级 24h 统计合约。
2. Demo `127.0.0.1:18088/gateway` 匿名市场连接成功（CONNECT `code=0`）；`N9NZV5/BTCUSDT` 订阅 ticker、最近逐笔成交、盘口初始快照，**三条订阅确认均 `Code=0000`**。
3. Demo 公开行情查询 `127.0.0.1:33002` 的当前 `N9NZV5/BTCUSDT` 产品数据成功，空数据不填假值。
4. API Docs EN/ZH 使用缓存中的本地 MkDocs 构建；新镜像从已发布 0.1.5 Docker 镜像衍生，避免依赖当时 DNS 故障的远程基础镜像。新镜像只包含 Python 方法文档和下载包，不公开源合同 YAML。
5. 镜像运行容器 `dc-saas-api-docs-1` 状态 `healthy`。公共 `/en/`、`/zh/`、0.1.6 Wheel / ZIP 均实际 HTTP 200，旧版 Wheel 可下载。

**尚不能宣称完成：**

- 真实 Gateway 在约 8–12 秒只读观察窗口内**没有出现实时市场通知事件**；订阅 ACK 成功不等于真实交易、盘口变化或 K 线连续推送已验收。需在正常有成交的 QA 产品上补可回放的流量与序号证据。
- 私有余额、持仓、订单状态、成交回报的**真实签名账户推送与断线重连**仍未完成端到端验收；本轮只验证了 SDK 权限合约及模拟通知数据。
- MD 1D 聚合不是严格滚动过去 24 小时，若产品承诺真正滚动 24h，需要在 MD 业务层另行实施并对齐 Web 与 SDK，不应仅调整文档描述。
- 资金流水没有独立已验证的推送源，所以本轮公开的是定时读取，而不是虚构的实时订阅。
- 租户 Web 最新用户、数据源、交易查询和管理页的双语修订已在 `bliplink/dc-saas-tenant-web` 源码分支提交并 Playwright 验证，但**尚未升级 Demo 租户 Web 镜像**；现网仍为 `local/dc-saas-tenant-web:product-matching-i18n-20261020`。Robot/API Key 管理端翻译仍需收尾。
- Order-only 模式未完成未入金交易员真实撮合、MD 推送、资金零变更的端到端验收。Common/Trade HA 验收在另一会话进行。
