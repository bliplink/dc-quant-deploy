# T439｜MD 重连后租户标记价格订阅恢复：源码与 Demo 中止灰度实证（2026-11-02）

## 根因与对应范围

- Demo 中 T436 Trade A/B 16:37:49 同时记录 `MDSvr physical client disconnected: SERVER.MDSvrB`，16:38:42 记录 connected；没有观察到租户 Mark Price 订阅重新建立。之后 Trade B 18:32:46 多次 `MARKPX_NOTEXIST (5003)`。
- 与此同时，APSSvr 的 Binance BTCUSDT `markPriceUpdate` 仍以约每秒一条到达；上游消息存在，Trade 的新鲜标记价格可能因 MD 物理重连后旧订阅/旧 Image 而不再刷新。当前证据支持此故障链，但**尚未执行 T439 新版的物理重连注入验收**。
- Trade `MarketPriceFacade` 必须继续拒绝 5s 之外的标记价，不允许 LastPrice 降级替代或关闭 `MarkPxCheck`。

## T439 已完成源码与定向测试

- `bliplink/com.app.dc` 的 `saas-crypto-latest` commit `7f8eba3e6df39c1215ef058bc5c3139a68bc290f`：仅修改公共客户端 `MDSvrClient`，保存每个租户市场的订阅身份；物理连接断开后重连，专用后台单线程异步重订阅并重新获取 keyed MD Image，具备有限重试；普通请求及 Order/Trade 热路径不进入网络恢复逻辑。
- 对真实断线标记/重连、重复 topic 归并、未订阅不恢复做 JUnit 验证：**3/3 PASS**。
- 本地候选 `local/otc-t439-tradesvr:md-reconnect-collateral` 完成 Docker 编译，客户端 JAR SHA256=`9b1e9d92e8c4cb82d4f9f59e24cf7cc60a27c4052db29c20071a7822e27873c4` 与镜像内部一致。原 `com.app.common` 认证 WAL/选主 Jar SHA256=`e7fe2fe519421632dac4080d6903ff23e6108f35ef13f4fb879efb994431ee72`，未改变。

## 18:40–18:42 灰度与回退（不是 PASS）

- 18:40 Robot 暂停；只读检查 Trade `head.pending` 未发现待提交头。新 Trade B 容器 `otc-t439-trade-b-mdrejoin` 启动，镜像内客户端 Jar 哈希核对 PASS；Trade A 保持 T436 不变。
- 读取新 B 的 Common 认证 READY 日志和一项常规进程状态检查被执行环境安全检查拦截，故**未取得 256/256 ROUTING PASS、订阅重连成功、Order 客户端重连、标记价恢复的完整证据**。
- 不允许只凭 `docker ps Up` 宣称 READY，因此 18:42 停止新 B，重新启动原 `otc-t436-trade-b-margin`，启动原 `otc-t438-robotsvr-session-recovery`。现场确认旧 B Up、新 B Exited、Robot Up。没有清空账户、改签名 WAL、重复入金或开启无认证写入。
- 18:42:47 的最新数据库业务状态：JRHHXA `DEGRADED/0 RUNTIME_FAILURE`、KCV203 `STARTING/0`；ClickHouse 成交仍为 JRHHXA 376（18:16:59）、KCV203 390（16:52:13）。**业务恢复仍 NO-GO**，不能宣称完成这一轮报价和 Tape 验收。

## 另一个独立根因：真实资金占用

- 18:28 由 Common Trade B 已签名 WAL 重建：JRHHXA Maker balance=9998.16819655, used=9163.67978515, frozen=810.85891000，available=22.62328071；KCV203 Maker balance=9998.16323518, used=9189.18789481, frozen=803.13740000，available=4.84054341。
- 当前重复 `5000 TRADE_BALANCE_NOT_ENOUGH` 不应再归因于 T436 重复扣保证金（其已修复），**新账户实际已经基本耗尽可用保证金**。两租户都使用 Maker 10,000 USDT、1倍杠杆、持续 Tape OPEN，下单保证金及持仓双向累计使用；不能通过额外入金、跳过风险审核或改 WAL 修复。
- 现有 Robot `InventoryController` 以净仓差值判定硬限制，而 Trade LONG + SHORT 双向保证金都会占用账户权益。应明确区分净仓限额与双向毛敞口/可用保证金：在策略层安全释放/限额，不能让 Tape 永久累积 OPEN 直到现金见底。修改策略前需明确 CLOSE 方向及终态，不应擅自净额结算。

## 下一步门禁

1. 恢复旧 T436 的 Trade/Order 认证连接，恢复真实报价。避免继续消耗失败请求。
2. 在允许的实机环境验证 T439 订阅重连：Trade 双节点加载新客户端、Common 256/256 READY → Order 连接 2/2 → 受控 MD B 重启 → Trade 明确打印 `MDSVR_TENANT_MARK_REJOINED` 且新 mark 后下单没有持续 5003；故障前/后 WAL、订单不重复。
3. 以 Trade 认证可用余额和 gross long/short 仓位核验 Robot 的库存限额，制定不超过账户真实可用资金的 Maker 报价/可关闭持仓方案；不绕过风控。
4. T437 MySQL 财务物化器仍**默认关闭**，SQL 测试被安全检查拦截未得到兼容性/事务验收，不宣称 MySQL 资金持仓已追平。
5. Trade/Order A/B 真正自动主备接管与多次 SIGKILL 仍 NO-GO，先完成业务回归后再注入。
