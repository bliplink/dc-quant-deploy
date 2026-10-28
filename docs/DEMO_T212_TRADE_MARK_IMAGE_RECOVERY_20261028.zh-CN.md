# T212｜Trade 标记价格失效自动恢复与 Robot 预验收（2026-10-28）

环境：Mac Demo、`saas-crypto`，本地 Java 8 / Docker 编译，不使用 GitHub Actions。

## 实际阻塞定位
- 2026-10-28 07:02–07:05，正式 Order→Trade Newing 回调多次 `code=5003`，在公共错误码里对应 `MARKPX_NOTEXIST`。
- 同期 APS 持续收到 BTCUSDT 币安 MarkPrice；正式 Gateway `MDSvr.queryPublicMarket` 对 `R0F6CC/BTCUSDT` 返回有效 `MarkPrice` 和 `IndexPrice`，盘口三次连续读取均有买卖盘 1/1 档。
- Trade `MarketPriceFacade.getMPrice` 首次同步订阅 MD Image 失败时会保留空缓存，后续风险请求仅从空缓存读取，没有重新请求；默认 5000ms TTL 继续生效。
- 因此该故障至少包含 Trade 失效缓存无法自愈的缺口；尚未证实 MD → Trade 的首次 Image 或实时 Topic 分发为何失败，不能仅靠代码静态检查认定链路完整恢复。


## 价格源澄清与本机代理实测（08:39）
- 默认数据源为 **BINANCE**：正式 APSSvr `enableBinanceFlag=true`、`enableMarkPriceFlag=true`，币安合约客户端日志确认 HTTP 代理 `192.168.5.2:10808`，行情 WebSocket 入口 `wss://fstream.binance.com/ws`。08:39:30 真实收到 BTCUSDT `markPriceUpdate`，不是网络无法连接。
- 正式 Gateway `MDSvr.queryPublicMarket(R0F6CC,BTCUSDT)` 返回标记价格和指数价格；数据库 `dc_tenant_symbol` 中该产品 `data_source_id IS NULL`，表示走默认产品 Symbol 的币安源；`dc_tenant_data_source` 对该租户尚无自定义源。
- 用户确认产品能力：APS 既可从币安收行情，也可接受租户自定义发布；数据源配置为 BINANCE/CUSTOM，绑定关系应允许来源 Symbol 与产品 Symbol 不同；未绑定数据源按币安默认处理，自定义有效期过期应停止使用过期价格，Trade 不得回退 LastPrice 或绕过风控。
- 当前 Admin 具备数据源配置表及 BINANCE/CUSTOM 的管理接口，但本轮源码审查未找到正式 APSSvr **自定义标记/指数价格发布 Handler** 的充分证据。MD 存在仅用于集成验收的 E2E Override，不能冒充正式 Broker 发布链路。正式自定义价格能力尚待独立 E2E 验收，不能把默认币安通过记为 CUSTOM 通过。
- 现阶段 `5003 MARKPX_NOTEXIST` 应优先在 MD→Trade 订阅/Image/缓存 TTL 一段定位，不应禁用 APS 币安连接或关闭严格风险检查。

## 本轮代码与验证
- Trade 源码 `.work/tradesvr/src/main/java/com/app/dc/service/price/MarketPriceFacade.java` 增加市场级限频后台订阅恢复：单线程、有界 64 队列、默认 10000ms 重试间隔；只有风险价格无效才触发；仍不允许从 LastPrice 回填风险标记价格。
- 新的 `MarketPriceFacadeTest` 模拟首次 Image 失败，检查立即拒单、异步恢复、恢复后接受 MarkPrice 与并发读不重复订阅。与旧的 FreshnessPolicy 一起 JUnit **4/4 PASS**。
- Trade 源代码在其 `saas-crypto` 本地仓已 commit：`9262106 fix(trade): retry stale MD mark image asynchronously with bounded recovery`。
- 本地 Docker 镜像：`local/otc-t212-tradesvr:mark-price-retry`，以运行中的 T205 镜像为基镜，仅覆盖新的 Trade 价格缓存类。
- 先滚动部署 Trade B：初次 Compose 重建缺少原 RSA 只读挂载，启动失败，故补齐原有 RSA A/B/public 只读挂载；最终 B 冷恢复日志 `TRADE_COLD_E2_SIGNED_OPEN_ORDER_REPLAY_ATTESTED partition:P246 frames:10 open:2`，`COMMON_GATEWAY_DISCOVERY_CERTIFIED`，重启次数 0。
- Trade A 滚动替换操作请求触发执行环境安全拦截，未执行。因此当前 **Trade A=T205，Trade B=T212**，不可声称完成 T212 全节点验收。
- 额外测试 Robot T211 `GatewayMarketDataClientTest`：Java 8 编译与 JUnit **15/15 PASS**，尚未发布 Robot 新镜像。

## 业务一致性与当前门禁
- 更早一轮的只读校验：Order P089 A/B 705 帧 WAL 相同，Trade P246 A/B 14 帧 WAL 相同；现存 OPEN_ORDER 2/2 逐笔同 Order 匹配；当前用户余额/持仓签名冻结保证金均 8.011375，手续费均 0.19227348。T212 滚动替换后的最新 RSA custody 仍应独立复核，不以旧 WAL 哈希代替。
- 2026-10-28 继续读正式 MD：连续 3 次 `PUBLIC_MD_IMAGE_PASS`，每次买卖 1/1，固定 update=11；这是行情读取通过，**不是 Robot 正在持续主动报价**。
- `R0F6CC` 下两只测试 Robot `e2e-depth10` 与 `t199-signed-live` 当前 `enabled=0`，避免未完成 Trade 价格恢复时制造重复拒单。
- **最终验收仍 NO-GO**：Trade A 升级、真实 MarkPx 恢复、Robot 持续刷新多档报价、正式 Maker/Taker 成交、资金/订单/成交/Projection 一致、Order/Trade A/B 自动双向故障切换均待做。

## 下一步（顺序不能倒置）
1. 在允许执行的环境中用当前完整 Compose 覆盖链补齐 Trade A 的原 RSA 只读挂载，升级到 T212；记录 Common 冷恢复与 Gateway 注册。
2. 以原租户、正式请求确认 `MARKPX_NOTEXIST` 不再反复出现；核实真正 MD → Trade 的持续 MarkPrice Topic 与 TTL。
3. 先用单只 Robot 受控 1x1 报价 → 真实 Maker/Taker 下单成交与撤单释放 → 10x10 连续多轮，并逐次读签名 WAL、账户、持仓、Projection。
4. 随后才允许 SIGKILL A/B，验证自动互切、恢复追平、不中断后账本一致，不允许双主、丢单、重复成交。
