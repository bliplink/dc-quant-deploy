# T228–T232｜Trade 认证业务接线、租户价格源恢复与真实成交阻塞

时间：2026-10-28 13:33 CST；Mac Demo 开发环境，`saas-crypto` 本地分支。**最终整体 NO-GO**；未使用 GitHub Actions，也没有宣布真实交易、财务一致性或自动 A/B 切换成功。

## 本轮实际提交/部署

1. Trade 签名业务运行接线：上一轮源码中 `TradeCertifiedLeverageAdmission`、`TradeCertifiedCloseNewingAdmission`、`TradeCertifiedCloseCancelAdmission` 未被打进运行镜像。这轮使用精确 class overlay 构建并上线 T228，同时在 A/B 同时开启三项认证入口。17/17 对应本地 JUnit 通过。仅支持无持仓/无挂单的安全杠杆修改和未成交 CLOSE 流程，**不等于已通过 CLOSE 实盘 E2E**。
2. T228 冷启动诊断：Trade P126 的 A 多 3639（认证 3638），P133 的 B 多 3032（认证 3031）。均为先前 Trade Writer 在拒绝阶段产生的一帧未认证尾部。先隔离机器人与 Order，停止 Trade A/B 且验明 ZK 无租约，脚本 `tests/t229_recover_trade_restart_P126_P133_uncommitted.py` 校验独立 RSA custody/双回执与提交索引，封存原始 WAL 后按双方真实认证水位恢复。证据：`/Users/kong/.opentradingcore/trade-ha-forensics/T229-Trade-P126-P133-20261028-131521`。**这是人工恢复而非 HA**。
3. 新租户产品目录发现 bug：Trade `DataFacade.getSymbol` 之前对所有新租户共用一个 60 秒负向 DB 重查窗口，造成其他租户先查后本租户新产品误拒绝 `TRADE_LEVERAGE_PRODUCT_NOT_ENABLED`。改成仅未发现的 `location + security_id` 独立 60 秒负缓存，最多 4096 个键，只有 DB 确认租户启用、试用有效、源启用时才放行。新增单测 `DataFacadeNegativeCatalogRecheckTest`，相关 11/11 通过；镜像 `local/otc-t230-tradesvr:scoped-product-recheck` 已 A/B 部署。两 Trade 与两 Order 认证冷回放及 256 分区路由正常。
4. APS Broker 价格 `ACCEPTED` 但 MD 的新产品无 MarkPrice：通过运行镜像字节码查到三个 MD 开关默认关闭，按 A/B 现有本机配置同时启用：
   - `broker.price.receive.enabled=true`
   - `broker.price.route.enabled=true`
   - `broker.price.event.publish.enabled=true`
   修改了 `/Users/kong/.opentradingcore/dc-saas-runtime-clean-20261016/control/overrides/MDSvr{A,B}/config/application.properties`，原文件均有同目录 `application.properties.pre-broker-price-t231-20261028.bak`。原有身份、数据源绑定和 TTL 校验不变。MD A/B 重启正常。
5. **真实新租户 T6ANNM** 经正式 Gateway/APS/MD 验证：自动审批、自定义源和产品、Broker 签名登录、两个交易员资金入账、Broker 自定义价格 -> MD 的 `MarkPrice=90001`，Maker 订单提交。此前 Z8YPGT 杠杆失败已由源码及 T230 修复；新租户 DK2QNB 通过了杠杆和两个账号各入金 1000。
6. 真实 Maker 原 `dc_orders` SQL 只读轮询会产生假阴性，因为该 MySQL 表现在 **总行数 0**（Projection 未接完整认证 Order 日志）。E2E 已改用 Maker 交易员登录会话调用 `OrderSvr.queryOpenOrder` 判断 `ClOrdID + OrdStatus=New`，但**成交后的数据库委托/成交 Projection 检查仍保持不变**。
7. **真实新租户 UR4KF7**：自动审批、自定义源和产品、Broker 签名价格 `MarkPrice=90001`、Maker/Taker 各 cashIn 1000、Maker 通过认证只读 QueryOpenOrder 为 `New`、Taker 已提交。认证 OrderSvr WAL P180：Maker 序列 1 Suspended → 2 New 非 maker → 3 New maker；Taker 序列 4 Suspended → 5 New 非 maker。**没有一笔真实成交**，`dc_orders_execorders` 该租户 last_qty>0 为 0，`dc_orders` 全局仍 0。确切撮合错误 `ORDER_COMMON_UNCROSSED_MAKER_WAL_NOT_COMMITTED`，根因 `ORDER_COMMON_CROSSING_QUOTE_NEEDS_ATOMIC_MATCH`。
8. **实际源码限制**：`CrossStrategy.matchOrder` 的 Common 模式仅允许非交叉 Resting Limit，Maker/Taker 真正交叉需要同一 Common 原子 WAL 中两个订单+执行结果的不可变 AFTER-state，且 Trade `OrderFacade.updateOrder` Common 模式直接拒绝 `ExecType=Trade`，资金持仓、手续费、冻结保证金、成交去重都缺认证结算。不能走老的 mutate-first cross/ProcessOrder，也不能绕过 WAL 或虚假生成成交。
9. 还有旧的 Order-only vs Trade-only 委托 Saga 差异，之前 T227 只读门禁记录 WSI1WX Order 多 2，R0F6CC Order 多 660；未做清理。自动 A/B 双向主切、旧 Writer 自动修复、Projection/资金一致性和 10/50/200 负载仍未验收。

## 最后一次真实状态（13:33 CST）

- Order A/B `local/otc-t225-ordersvr:certified-common-window` RUNNING/0 restarts；Trade A/B `local/otc-t230-tradesvr:scoped-product-recheck` RUNNING/0 restarts；MD A/B、Robot 亦 RUNNING/0 restarts。
- 8 个已启用的 Robot 都 `RUNNING`：DK2QNB 40、G6IQ8E 40、R0F6CC 2、T6ANNM 40、U6ZAMX 40、UR4KF7 40、WSI1WX 40、Z8YPGT 40 个挂单。
- 所有新增 Broker API Key 均由测试 finally 尝试撤销，E2E 只使用正式 Gateway，不直接写数据库。
- **必须优先完成** Order 跨多订单认证匹配事务 + Trade 的认证 Maker/Taker 财务 AFTER-state 和 outbox/Saga 投影，否则真实交易无法 PASS，不能对外宣布 Demo 可交易。
