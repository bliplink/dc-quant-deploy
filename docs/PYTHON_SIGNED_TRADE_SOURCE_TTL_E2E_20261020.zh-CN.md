# 2026-10-20 Python SDK 签名交易及自定义价格源切换验收

## 1. Python Broker + Trader API 真实交易（已通过）

在 Mac mini 现有 Demo 容器，以 0.1.7 **本地候选源代码**执行：

```bash
PYTHONPATH=.work/sdk-realtime-probe-deps:.work/sdk-realtime-017/sdk/python \
  python3 tests/test-custom-product-live-e2e.py --execute --with-traders --sdk-signed
```

返回码 `0`，独立自动审批租户 `TO89QP`。租户自建并绑定 `BTC003USDT` 产品和价格数据源；Broker SDK 正常签名登录，发布 `index=90000`、`mark=90001`；两个独立 Trader 自助创建 API Key、签名登录并经 WEB Session 入金各 1000；Maker/Taker 两笔真实委托均为 `Filled`，**两条成交回报**。SDK `balances()`、`positions('BTC003USDT')`、`order_history(symbol=...)`、`execution_history(symbol=...)` 均成功。Maker 空头 `0.001`，余额 `999.98200000`；Taker 多头 `0.001`，余额 `999.94600000`；测试 Trader API Key 和 Broker API Key 全部成功回收。

此前同类运行租户 `YA9MVK` 两笔交易已真实成交，但调用旧 SDK 无参数 `positions()` 返回后端 `9000`，不是资金/持仓缺失。确认 `TradeSvr.QueryTradePositionHandler` 要求 `securityid` 必填，已经在 SDK **0.1.7 候选源码**修为 `positions(symbol)`，增加精确 wire 参数单元测试。此候选已在独立 GitHub 分支提交，不是公开部署的 0.1.6 wheel。

## 2. 自定义价格源切换及 TTL（已通过）

执行：

```bash
python3 tests/test-price-source-switch-live-e2e.py --execute
```

返回码 `0`，独立租户 `SYU7KT`，仅创建产品/来源和临时 Broker Key，没有订单或资金变更：

1. 源 A 标记价 `90001`，APS 发布后 MD 成功查到。
2. AdminSvr 对 `BTC003USDT` 执行 `BIND` 到源 B，MD 旧 MarkPrice 清除。
3. 已切走的源 A 再次发布 `92000`，产品报价依然无有效 MarkPrice，**无旧来源回退**。
4. 源 B 发布 `110000`，相对最初值偏差约 **22.22%**，MD 成功接受，不使用 1% 切换前偏差限制。
5. 源 B TTL `15000ms`，到期后 MD 标记价格变为无效，**没有回退到过期/已解绑定的 A**。
6. 临时 Broker API Key 关闭 `code=0`。验收脚本只允许本地 Demo endpoint；只通过服务接口写入；不直接写 DB。

先前独立租户 `XS99IM` 的首个一次性初始报价虽被 APS 接受，但 35 秒内 MD 未显示有效 MarkPrice，初次测试未通过。新脚本对**无交易副作用的价格更新**支持在新建产品目录异步同步时递增 sequence 重发布；`SYU7KT` 实际首次报价即成功。暂未据此确认前述现象根因已经消除。

## 3. 私有订阅未通过、且必须继续验收

命令：

```bash
PYTHONPATH=.work/sdk-realtime-probe-deps:.work/sdk-realtime-017/sdk/python \
  python3 tests/test-custom-product-live-e2e.py --execute --with-traders \
  --sdk-signed --verify-private-streams
```

QA 租户 `DHFYX8` 中，Broker 与两名 Trader API Key 已签名登录、两笔测试资金已入账、MD 标记价已就绪，但在订单发出**前**，首次 `AccountStreams.connect()` 的私有 Gateway WebSocket TOKEN 连接等待中出现 `WebSocketTimeoutException`。两个 Trader API Key 和 Broker API Key 均已回收。因此**不可声称私有成交/资金/持仓推送或断线重连完成**。此前 SDK 0.1.6 还把带 `*` 市场指标段的执行订阅与实际完整 topic 直接比较，合法事件会被过滤；SDK 0.1.7 候选修复为仅逐段匹配单个 `*`，仍严守用户/租户界限（39/39 单测通过）。需排查 `LoginSvr` API TOKEN 的 WebSocket 登录处理或 Gateway 会话路由，再做实际私有事件及重连恢复验证。

## 4. 订单持久化个别失败：独立保留，不掩盖

执行扩展 ORDER_ONLY/价格源测试时，独立 QA 租户 `KMQ5U3` 的 `OO-3E9093F4FA-MAKER` 接单 API 返回成功，但 35 秒内 `dc_orders` 无该 `clord_id`，事后读库本租户订单仍为 0；没有继续下对手盘或切价格源。OrderB 日志记录 `ORDER_COMMAND_REPLICA_SLOW`（相同 CID 的 seq 22/23）及 `ORDER_NEW_BATCH_SLOW`，没有足够证据确定是 Order 状态、Projection 数据缺失还是异步链路异常。单独的订单/Projection 可靠性追踪未关闭，不能据此宣称订单“无丢单”已验收。正式 ORDER_ONLY 两笔成交及账本隔离通过证据请见 `docs/ORDER_ONLY_LIVE_MATCH_EVIDENCE_20261020.md`。

## 5. 提交边界与后续

SDK 修复 branch：`bliplink/opentradingcore-api-docs` → `codex/python-realtime-methods-sdk-017-20261020`（private wildcard 与 `positions(symbol)`）。保留正式公开 SDK 0.1.6，**本轮没有重新发布 API Docs 容器、也没有使用 GitHub Actions**。当前应继续完成私有 WebSocket 签名会话握手、行情重连后 snapshot/diff 连续性、Order/Projection 接单即持久化的证据、再推广 SDK 0.1.7。测试期间如新租户数据出现问题，不需要为恢复临时 QA 账户停滞，但不可把失败当成通过。
