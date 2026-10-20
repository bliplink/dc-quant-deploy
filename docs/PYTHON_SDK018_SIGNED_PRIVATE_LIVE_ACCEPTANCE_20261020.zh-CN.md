# 2026-10-20 Python SDK 0.1.8 / 私有实时完整验收

## 发布与 API 入口

Python SDK 正式对外仅描述一个类 `OpenTradingCoreClient`，通过 `.public(base_url, location)` 获取公开查询/实时行情，通过 `.from_api_key(base_url, api_key, api_secret, location)` 登录 Trader 或 Broker。公开方法均以 `OpenTradingCoreClient` 为前缀；MarketStreams、AccountStreams、PublicMarketClient 只作为现有内部兼容实现，不再写入正式 API Docs 方法列表。

API Docs 仓库 `bliplink/opentradingcore-api-docs`：分支 `codex/python-realtime-methods-sdk-017-20261020`，最新版提交 `1b7b092` (`[skip ci]`)。修复：
- `OpenTradingCoreClient` 为所有查询/下单/账户/价格发布/实时订阅的统一对外入口。
- 本地 REST 端口 33002、实时升级端口 18088 不同时，通过 `connect_stream('private', gateway_base_url='http://127.0.0.1:18088')` 指定实时入口；签名连接强制同主机同协议，防止泄露 Token 到别的站点。
- TOKEN WS 登录会消费旧 Session 并返回新 SID。SDK 在验证租户、用户身份后同步替换自己的 Session Token，保证随后 HTTP 查询/下单不再使用失效凭证。
- SDK 客户端私有成交主题使用单段 `*` 通配符匹配服务端真实 market indicator（实测有 0、1），且用户 ID 与 tenant 段必须精确匹配，不能跨账户推送。
- `positions(symbol)` 使用 TradeSvr 必需的 `securityid`；行情独立于数据源 ID；生成文档保留中英文限流、错误码、枚举、参数章节。

本地 44 项 SDK 测试 + 4 项双语公共章节测试通过，双语 MkDocs `--strict` 通过。0.1.8 Wheel 已生成并直接安装到单独目录做实际交易测试。对外已部署镜像 `local/dc-saas-api-docs:python-single-client-018-20261020`，容器 `dc-saas-api-docs-1` 为 `healthy`。公网 `https://api.opentradingcore.com/en/`、`/zh/` 返回 200；实际 `pip install https://api.opentradingcore.com/sdk/opentradingcore-0.1.8-py3-none-any.whl` 成功。保留 0.1.6 和 0.1.7 wheel。不曾调用 GitHub Actions，只重建 API Docs 容器，不触碰生产交易容器。

## 真实交易 + 私有流完整 PASS

命令（只在可控 QA Demo、明确 `--execute` 下运行）：

```bash
PYTHONPATH=.work/sdk-realtime-probe-deps:.work/sdk018-installed \
python3 tests/test-custom-product-live-e2e.py --execute --with-traders --sdk-signed --verify-private-streams --near-simultaneous
```

QA tenant `MVH51T`：自定义产品 `BTC003USDT`、绑定自定义 Broker 价格数据源，Mark 90001。Broker 签名登录、两名 Trader 签名登录、各入金 1000，私有会话新 Token 轮换后立即通过 `sdk.balances()` 校验。四个主题注册。Maker 卖出与 Taker 买入下单启动相差 0.319ms，两张 `Filled`，2 笔真实成交由 Projection 入库。两名 Trader 分别收到：`dc.order.status`、`dc.order.trade`、`dc.trade.accountbalance`、`dc.trade.position` 的本租户本用户真实通知；跨账户未接收。Maker Short 0.001 余额 999.98200000，Taker Long 0.001 余额 999.94600000。再次通过已安装 SDK 执行余额、持仓、历史订单、历史成交查询成功。临时 Trader API Key、Broker Key 全部清理。整条验收 PASS。

另外租户 `KP8TIU` 也收到 2 张 Filled、2 笔成交和所有四类私有推送，但当时测试脚本仍使用轮换前 SID 作额外直连 Trade 读请求，触发 1003（旧 Token）；已修正测试脚本。`Z8WGEY` 的订单与四类私有推送也真实到达；彼时测试脚本错把成交 market indicator 固定为 4，之后修正为单段通配匹配。

## 仍未完成，需优先修复

**Order-Trade-Projection 偶发悬挂：** `EMYDWC` 的 `CUSTOM-F63F536718-MAKER` 下单请求得到成功回复，但 60 秒内未出现持久化 `New` 订单，读取 MySQL `dc_orders` 不存在。Order-B `ORDER_NEW_ADMISSION_SLOW` ~1960ms，其中同步复制 ~1931ms；Trade-B 已记录 `TRADE_UPDATE_ORDER_PHASE ... execType:Newing status:Suspended ... success:true` (~775ms)，Order-B `TRADESVR_UPDATE_ORDER_CALLBACK_SLOW` ~1003ms。Order 命令 WAL/复制不等于订单业务最终提交，需核对异步回调是否投递、排队、提交；不能直接重放结果不明的委托。此前 `KMQ5U3` 亦出现类似异常。当前未实现完整自动恢复/告警，也未通过重启恢复后权威一致性。

需额外验证：私有 WS 断线重连、重新订阅、Snapshot/差量恢复，Order/Trade A/B 自动主切、落后副本追平、权限隔离、无双主、无丢单无重复成交、10/50/200 租户压力及持续稳定性。单次端到端成功不等于 HA 已验收。
