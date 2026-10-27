# T202–T204｜Common E2 真实 Trade 持仓/资金恢复、冻结风控门禁

Mac mini Demo｜2026-10-28（Mac 本机时间）｜本地 saas-crypto｜未使用 GitHub Actions。**完整交易与 HA 仍 NO-GO。**

## 本次真实执行及证据
1. T202 TradeCold E2 签名回放后、发布 Gateway READY 前，逐条重建 OPEN_ORDER UPSERT/REMOVE 的期望索引，与 OrderManager.snapshotLocation 真实内存的 ID、用户、产品、方向、价格、数量、状态对照；不一致直接拒绝启动。Trade A/B 都真实重建，日志均确认 TRADE_COLD_E2_SIGNED_OPEN_ORDER_REPLAY_ATTESTED partition:P246 frames:4 open:4，Gateway 注册正常。
2. 新增只读审计 tests/t202_readonly_signed_trade_order_crosscheck.py：Order P089 / Trade P246 双物理 WAL 对照，4 个 Trade OPEN_ORDER 全部与 Order 当前 Maker 的租户/用户/产品/方向/数量/价格/Demo 匹配，持仓冻结数量及名义金额覆盖 4 单。另用原钉扎 RSA 公钥验收真实 A/B 2/2 custody，Order 676 帧、Trade 7 帧，未伪造证书。
3. T203 根因：TradeStart.run 在 Common 已回放签名 WAL 后仍执行旧 AccountBalanceFacade.init 和 PositionFacade.init；前者从旧 MySQL 覆写签名账户冻结值，后者还可写回 DB。Common 模式禁止这两次旧 DAO 重载，单节点非集群模式保留原行为。Trade A/B 冷重启均显示 SIGNED_BALANCE_STATE_OWNS_STARTUP、SIGNED_POSITION_STATE_OWNS_STARTUP，并同时通过 T202 认证状态回放。
4. T204 在新的 Common 认证 OPEN Newing 入口增加 O(1) fail-closed 检查：账户冻结保证金和手续费均不得小于此用户产品的签名持仓冻结额，若不足拒绝新的开仓，不修改原始 WAL、不增加 ZK 热路径。相关九项 JUnit 回归 PASS。
5. 当前原始 Trade E2 签名财务差额：Position freezedMargin=16.02133，AccountBalance freezedMargin=8.009955，账户少 **8.011375 USDT**；Position freezedCommission=0.38451289，AccountBalance freezedCommission=0.19223941，账户少 **0.19227348 USDT**。没有修改历史签名 WAL、没有重复入金、没有直接改 MySQL 抹平差异。之前 DAO 覆盖缺陷能解释状态回退，但仍需进一步核对实际形成时序。
6. 原始 3 笔 CashIn 不可变前缀、真实 MySQL 流水与余额的只读核对 PASS；当前问题为冻结准备金缺口，不是现金入金丢失。
7. 真实运行 Order T201d A/B、Trade T204 A/B；Order 两边 664 条活动订单；仅签名 Primary（Order B）持续发布恢复的市场 Image，Replica（Order A）不双发。

## 仍未验收通过
- 真实 cancelBatchOrder / Order Pending_Cancel→Trade 四域释放→Order Signed REMOVE 未取得 E2E 成功。早前 T201 真实测试返回 TRADE_CANCEL_ORIGINAL_RESERVATION_NOT_FOUND，T201b/T201d 修复后另一次 Robot 写入探针遭执行环境安全检查拦截，不能宣称撤单 PASS。
- 存量的财务冻结不一致必须进行 Common 签名、可审计的修复；或者在用户已明确同意的 Demo 重置流程中保留旧证据并重新建租户。严禁修改现有 WAL 原件或用数据库直接覆盖证据。
- MD 实际收到/安装 Image 和终端匿名盘口、真实成交与资金/持仓/委托/成交/Projection 完整一致、Robot 1x1→10x10 多轮报价、SIGKILL 自动 A/B 双向切换仍待测试。
- 测试 Robot R0F6CC/e2e-depth10 及 R0F6CC/t199-signed-live 两者 enabled=0，未持续重试，不造成额外未释放挂单。
- 相关代码已提交本地 saas-crypto；远端与本地 commit 祖先分叉，未强推远端或调用 GitHub Actions。

**最终状态：签名业务恢复 PASS；存量财务冻结 NO-GO；持续 Robot、真实成交、自动 HA NO-GO。**
