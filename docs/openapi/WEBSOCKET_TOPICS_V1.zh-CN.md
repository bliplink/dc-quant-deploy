# DC Open API v1 WebSocket / Topic Reference

当前基线：2026-09-28。

本文锁定 Crypto Open API v1 的公开实时 Topic、订阅初始 image、增量序列、Gap 检测和断线恢复语义。未列入本文的内部 Topic 不属于 v1 公共兼容契约。

## 1. 连接与认证

Trader API 标准流程：

```text
1. signed HTTP POST /api -> LoginSvr/apiKeyLogin
2. 获取 authoritative user_id/location + sid/token
3. TCP/WebSocket CONNECT 到 GW
4. clientType/client_type = API
5. pwd/token = LoginSvr 返回的 sid/token
6. request / subscribe
```

Tenant Service 使用同一流程，但 `client_type=TenantAPI`。

Broker API Key 同样使用 `client_type=TenantAPI`，但同时具有：

```text
api_key_type = broker
```

Broker Session 的 actor 是 Broker 自己；私有 Topic 中的目标 UserID 可以是当前 Broker location 内被授权 customer。

连接失效或 `9002 / USER_SESSION_NOTEXIST` 后，不继续重用旧 sid；重新执行 signed API-key login，再连接和恢复订阅。

## 2. Topic 身份规则

Topic 中的 `<Location>`、`<UserID>` 必须满足 Session 权威 scope。

Trader：

```text
Topic UserID == Session user_id
Topic Location == Session location
```

Broker：

```text
Topic Location == Broker Session location
Topic UserID == Broker 当前 location 内被授权 customer
```

Tenant Service Key 不能借由 Topic 指定 customer 来获得 Broker/Trader 私有流。

服务端必须拒绝跨租户和无权限 customer 的订阅。

当前 Crypto 基线默认：

```text
MarketIndicator = 4
```

当前 Topic 名称尚未显式编码 marketIndicator；多市场兼容方案仍是 GA 剩余项之一。因此 v1 当前只能在同一 location 下把同名 SecurityID 视作 Crypto market=4。

## 3. Public Market Topics

| Topic | 类型 | 初始 image | 序列/恢复 |
| --- | --- | --- | --- |
| `dc.md.orderbook.<SecurityID>.<Location>` | Top-N 兼容 OrderBook | 是；空市场也返回空 image | `lastUpdateId`；适合 UI，不建议用于严格增量重建 |
| `dc.md.depth.snapshot.<SecurityID>.<Location>` | Depth recovery snapshot | 是 | `lastUpdateId` |
| `dc.md.depth.diff.<SecurityID>.<Location>` | Depth incremental | 当前最新 diff + 后续 live | `firstUpdateId/finalUpdateId/previousFinalUpdateId` |
| `dc.md.bookticker.<SecurityID>.<Location>` | Best bid/ask | 有缓存时返回 | `lastUpdateId`；change-driven，不是 heartbeat |
| `dc.md.depth.partial.<Depth>.<SecurityID>.<Location>` | Partial depth image | 有缓存时返回 | `lastUpdateId`；SaaS 当前启用 depth=10 |
| `dc.md.trade.<SecurityID>.<Location>` | 标准化 trade stream | 有最新成交时返回 | 无公开连续 sequence |
| `dc.md.market.trade.<SecurityID>.<Location>` | market trade stream | 有最新成交时返回 | 无公开连续 sequence |
| `dc.md.kline.<Interval>.<SecurityID>.<Location>` | Kline | 是，当前 snapshot 查询最多 1000 条 | 无公开连续 sequence |

所有行情 Topic 要求 `MARKET_READ` 或当前允许的 public-tenant market 访问。

## 4. Depth image / incremental 语义

### 4.1 Snapshot

`MarketDataSnapshotFullRefresh` 的关键字段：

```text
SecurityID
MarketIndicator
Location
MDBookType
LastUpdateId
NoMDEntries[]
```

Entry：

```text
MDEntryType = 0  -> bid
MDEntryType = 1  -> ask
MDEntryPx
MDEntrySize
MDPriceLevel
```

### 4.2 Delta

`MarketDataIncrementalRefresh` 在 snapshot 字段之外增加：

```text
FirstUpdateId
FinalUpdateId
PreviousFinalUpdateId
```

数量规则：

```text
MDEntrySize > 0  -> 插入/替换该价格档数量
MDEntrySize <= 0 -> 删除该价格档
```

### 4.3 Gap 检测算法

客户端维护本地 `lastUpdateId`：

```text
收到 snapshot:
    local = snapshot.lastUpdateId

收到 delta:
    if delta.finalUpdateId <= local:
        ignore duplicate/old delta

    else if delta.previousFinalUpdateId != local:
        GAP
        discard local depth
        reacquire snapshot
        local = snapshot.lastUpdateId

    else:
        apply delta entries
        local = delta.finalUpdateId
```

不要仅凭 WebSocket 到达顺序假设深度连续；必须使用 updateId 链验证。

## 5. Trader Private Topics

| Topic | Scope | Subscribe image | Live payload |
| --- | --- | --- | --- |
| `dc.order.status.<SecurityID>.<UserID>.<Location>` | ORDER_READ | 当前订单列表 | `ExecutionReport[]` |
| `dc.order.trade.<SecurityID>.*.<UserID>.<Location>` | ORDER_READ | 当前可查询成交 image | `ExecutionReport[]` |
| `dc.trade.accountbalance.<UserID>.<Location>` | ACCOUNT_READ | 当前 `AccountBalanceReport` | 最新 balance state |
| `dc.trade.position.<UserID>.<Location>` | ACCOUNT_READ | 当前 `PositionReport[]` | `PositionReport[]` |

外部 Trader execution 推荐使用 `tradeFlag=*`。内部 maker/taker 分流值不作为 v1 外部兼容要求。

Position stream 可能先发布：

```text
RiskStatus=PENDING_RECALC
RiskValid=false
```

随后 RiskEngine 发布新的 VALID/INVALID derived-risk state。客户端应以最新 PositionReport 为准，不把第一条 PENDING_RECALC 当作最终强平风险结果。

## 6. Broker Private Topics

Broker 和 Trader 复用同一套订单、成交、余额、持仓 Topic 语义，但 Broker 的目标 UserID 是 customer。

当前 Broker E2E 已真实验证 customer execution topic：

```text
dc.order.trade.<SecurityID>.*.<CustomerUserID>.<Location>
```

例如：

```text
dc.order.trade.BTCUSDT.*.customer-user-id.ABC123
```

Broker 可以为同一 location 下不同 customer 建立独立订阅。

推荐 Broker 客户端维护：

```text
customerId -> subscriptions -> local state
```

每个 customer 的订单、成交、资金、持仓状态必须独立维护，不能把不同 customer 的私有事件混成 Broker actor 自己的账户状态。

Broker 私有 Topic 必须满足：

- Broker key 当前有效；
- Broker 拥有所需 ORDER_READ / ACCOUNT_READ；
- customer 属于 Broker authoritative location；
- customer 有效；
- Topic location 与 Broker session location 一致。

跨 location customer Topic 必须拒绝。

### Broker disconnect / reconnect

Broker 断线后：

```text
signed apiKeyLogin
  -> new Broker session
  -> reconnect GW
  -> for each active customer:
       queryOpenOrder
       queryAccountBalance
       queryTradePosition
       query history when needed
       resubscribe private topics
```

不能假设断线期间的所有 private events 可以只靠重订阅补齐。

---

## 7. Private stream 没有全局 sequence

订单、成交、余额、持仓 Topic 当前没有公开的统一 monotonic sequence。因此 v1 **不承诺**客户端能够只靠事件流无损补齐任意断线窗口。

断线恢复必须按权威状态恢复：

```text
re-authenticate
    |
    v
reconnect GW
    |
    +--> queryOpenOrder / history as needed
    +--> queryAccountBalance
    +--> queryTradePosition
    |
    v
resubscribe private topics
    |
    v
treat new subscribe image / latest query result as authoritative
```

客户端不得通过“本地上一条事件 + 猜测丢失事件”恢复资金或持仓。

## 8. Market stream 重连

对于 snapshot 型 topic（orderbook/bookticker/partial/kline）：

1. 重连；
2. 重新订阅；
3. 用新的 image 覆盖本地状态。

对于 depth diff：

1. 重连；
2. 获取新的 `dc.md.depth.snapshot...`；
3. 设置 `local=lastUpdateId`；
4. 重新接收 `dc.md.depth.diff...`；
5. 每条 delta 严格验证 `previousFinalUpdateId == local`；
6. 再次发生 Gap 时重复 snapshot rebuild。

## 9. Change-driven 不是 heartbeat

以下流可能在业务状态不变化时保持安静：

- bookTicker；
- order status；
- account balance；
- position。

“长时间没有消息”本身不等于连接断开。连接活性应由 GW transport heartbeat/connection state 判断，业务 freshness 由 SDK 按 Topic 类型单独处理。

## 10. Subscribe image 与 live event

当前 MDSvr/OrderSvr/TradeSvr 的公开 Topic handler 会在订阅阶段返回当前 image（若该 Topic 当前有状态）；订阅成功后再接收 live publish。

外部 SDK 必须允许以下合法情况：

- 空订单簿返回 `lastUpdateId=0` + 空 entries；
- 尚无成交时 trade topic 没有 image；
- 尚无 position 时返回空列表；
- image 后很快出现 live update。

## 11. 当前不属于 v1 公共 Topic

以下虽然可能存在于内部系统，但 v1 外部客户端不得依赖：

- `dc.order.depth.*`（OrderSvr -> MDSvr 内部恢复链路）；
- APSSvr / Binance adapter 原始 Topic，如 `dc.bookticker.BNFutures.*`、`dc.aps.depth.*`；
- `dc.trade.posting.*`，直到其外部 scope/sequence 契约单独冻结；
- `dc.cancelreject.*`，直到其公共 request/reply 与 stream 语义单独冻结；
- 未列入本文的通配内部运维 Topic。

## 12. SDK 必须实现的恢复职责

Java/Python SDK 后续至少必须封装：

- signed API-key login；
- Session connect；
- subscribe/unsubscribe；
- 自动重认证；
- 自动 resubscribe；
- depth snapshot + diff Gap recovery；
- private state re-query；
- rate-limit / public error mapping；
- duplicate/old depth delta 忽略；
- Trader topic identity 由 authoritative user/location 构造；
- Broker topic identity 由 authoritative broker location + authorized customer user 构造；
- Broker 多 customer 订阅隔离；
- 跨 location customer topic 拒绝。

因此应用开发者不需要直接实现上述恢复状态机。
