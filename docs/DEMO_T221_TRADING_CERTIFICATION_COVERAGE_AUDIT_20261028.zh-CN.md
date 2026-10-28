# T221｜Demo 新租户、自动 Robot、自定义价格与真实成交认证链路审计（2026-10-28）

## 测试基线

固定现有镜像，不重新部署 Order/Trade/Common：
- Trade A/B: local/otc-t220-tradesvr:push-only-md-topic，running，重启次数 0。
- Order A/B: local/otc-t209-ordersvr:certified-newing-cancel，running。
- APS: local/otc-t219-apssvr:binance-mark-1s；既有配置开关 broker.price.publish.enabled=true（仅启用已有 VerifiedBrokerPricePublisher，无业务代码变更）；原配置备份于 /Users/kong/.opentradingcore/dc-saas-runtime-clean-20261016/control/overrides/APSSvr/config/application.properties.pre-broker-e2e-20261028.bak。
- R0F6CC/t199-signed-live 保持 RUNNING；前一轮受控人工恢复的 Common P246 证据位于 ~/.opentradingcore/trade-ha-forensics/T220-P246-20261028-105400。

## 真正执行的 E2E

正式入口：python3 -u tests/test-custom-product-live-e2e.py --endpoint http://127.0.0.1:33002/httpapi/ --execute --with-traders

| 运行 | 新租户 | 通过 | 首个阻塞 |
|---|---|---|---|
| 第一轮 | WSI1WX | 自动审批、管理员登录、自定义源和产品、匿名可见、租户隔离、切换数据源、Broker Key 与签名登录 | APS Broker price 9000；当时既有发布开关未显式启用 |
| 第二轮 | U6ZAMX | 前述全部 | APS 9000；请求发生在 APS 重启完成之前（11:15:20），Spring 11:15:42 才启动完成 |
| 第三轮 | G6IQ8E | 前述全部，**Broker 价格发布返回 code=0 / ACCEPTED** | TradeSvr.setLeverage 返回 1003：TRADE_COMMON_DURABLE_WAL_ACK_NOT_CONNECTED |

三租户均为 TRIAL，**自动产生并启用 trial-liquidity-BTCUSDT Robot，各 RUNNING，open_order_count=40**；正式 MD queryPublicMarket(BTCUSDT) 每租户均有 10 档 Bid + 10 档 Ask 及有效标记价格。以上为三份真实 Gateway / MySQL / MD / Robot 的核验结果，不是隔离单元测试。

## 单一业务集成缺口，不要再修改 Gateway/MD/Robot

Trade 在 Common nodeRuntime READY 时严格禁止旧 mutate-first WAL 路径，这是正确的防护：
- src/main/java/com/app/dc/service/state/TradeStateCoordinator.java 的 requireWritable() 在 Common 启用时一律拒绝 executeMutation()。
- src/main/java/com/app/dc/handler/SetLeverageHandler.java 仍调用 executeMutation() + DataFacade.updateSymbolLeverage() + TradeConfigurationStateRecorder.recordLeverage()，因此 1003。不能为通过测试而打开旧 mutate-first。
- src/main/java/com/app/dc/service/order/OrderFacade.java 的认证模式只允许 Newing/OPEN 和 Trade_Cancel/Cancelled/OPEN；撮合成交产生的 ExecType=Trade 走 TRADE_COMMON_UNCERTIFIED_BUSINESS_PATH_DENIED，故 Maker/Taker 成交尚无法获得正式 Common 认证 ACK。
- CashInHandler 已有 TradeCertifiedCashInAdmission，且 Common 认证写入要求 Info1 稳定幂等请求号；已修复 test-custom-product-live-e2e.py 的现金测试参数（仅测试脚本更改，无生产代码更改）。
- CashOut、SetAccountConfig、SetPositionType 等旧 mutate-first 管理写路径同样需在上线前逐项盘点，不得当作已验收。

已有 TradeStateMutation.ACCOUNT_CONFIG、SYMBOL_PARA、ACCOUNT_BALANCE、POSITION、OPEN_ORDER、DEDUPE_RESULT、POSTING 模型和 TradeRecoveryApplier typed replay；不必再造状态机/复制协议。

## 集中修复范围（唯一可接受的实现）

1. **Trade 配置写入**：纯函数准备杠杆变更后的 SYMBOL_PARA + 受影响 POSITION/ACCOUNT_BALANCE；使用 TradeStateCoordinator.commitPreparedState，由 Common 完成真实双物理 WAL/Custody/RSA ACK 后才 apply，持仓状态和幂等重放要同一来源。
2. **Trade 成交回报**：将 ExecType=Trade 的开平仓财务结算、Maker/Taker 费用、持仓、余额、原委托剩余量、成交去重和必要 Posting 改为先准备一组完整、租户隔离、确定性 AFTER-state，然后经同一 Common 提交，再执行 apply；绝不在 Common fsync/custody 之前 mutate。
3. **正式业务回归**：全新租户自动审批+Robot 10x10→ Broker API 自定义价格 publish/MD TTL→两名交易员注册/入金/设置杠杆→Maker GTC 新单→Taker 撮合成交→订单/成交/余额/持仓/Projection 完全一致→撤单/平仓。必须检验异常、部分成交、重复回调的无双扣/漏扣。
4. **HA 故障注入**：在持续实际撮合的情况下真实停止 B、恢复追平、A/B 双向自动主切；认证 Writer poisoned 后不能简单清 flag，也不能人工修 WAL 算自动恢复。严格核对 ZK epoch、旧主隔离、签名提交、授权、资金/持仓/订单/执行与 projection 一致。

整个业务适配层都归 Trade，Common 仍是唯一集群机制。未通过真实两人撮合与自动 HA 前，整体 Demo 维持 NO-GO。

## 操作边界

测试没有重建 Order/Trade/Common，没有修改真实生产密码，也没有运行 GitHub Actions。三次自动审批测试会留下独立 TRIAL 租户及其 Robot，这些是正式业务证据，清理前需先完成验收并判断是否还需要复用。Broker E2E 临时 Key 已由脚本在 finally 中撤销。禁用任何绕过授权的方式，不用空密码或改租户注册策略来造成功记录。
