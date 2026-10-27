# T205｜四笔真实订单的原始冻结准备金一次性补齐

日期：2026-10-28（Mac Demo）｜saas-crypto｜不调用 GitHub Actions。

## 修复器与严格前置条件
- TradeCertifiedReserveRepair 默认为禁用。仅识别 R0F6CC / robotmaker / BTCUSDT、四笔原已签名 OPEN_ORDER、原账户冻结保证金 8.009955、原账户手续费冻结 0.19223941。
- 逐笔确认四张订单的冻结数量/原价金额合计与原签名 Position 完全相等；只支持这一份原始 Demo E2 状态，不适用于其它用户。
- 先读取真实 Primary/Common 分区锁，成功后构造单个 ACCOUNT_BALANCE UPSERT after-state，不创造新现金、成交、入金、历史日志删除、人工 MySQL 调整。
- 通过 TradeStateCoordinator.commitPreparedState 交给 Common 真实物理 2/2 WAL/custody，再使用 Common 返回的签名原始字节更新当前业务内存。
- 不确定提交结果绝不自动重试，原始 head 不匹配则拒绝。已完成态会拒绝再次写相同准备金。
- Java8 全量编译，本地离线镜像成功，四项精确场景 JUnit PASS。

## 已执行的 Demo 证据
1. 执行前，原 Common RSA 只读物理证书验收：Trade P246 原始 7 帧、Order P089 原始 676 帧；A/B 字节 SHA 相等，真实 RSA 双签；Trade 4 笔 OPEN_ORDER 与 Order 4 Maker 的金额/数量/租户/方向/价格等严格匹配。旧 Trade 原始冻结差额 8.011375 USDT 保证金、0.19227348 USDT 手续费。
2. T205 代码已部署到 Trade A/B，两节点分别完成真实冷恢复认证，运行正常。B 保持修复开关关闭。
3. ZooKeeper 真正的 P246 manifest 标识 TradeSvrA 为 Primary。仅在 A 本地 ready.properties 临时装备精确修复参数，并备份旧配置；带真实 Common 配置滚动重启 A。2026-10-28 06:31:34 的服务日志返回：TRADE_DEMO_RESERVE_RECONCILE_COMMON_DURABLE_OUTCOME committed:true。
4. 本次运行后**已将 A 的修复开关重新置为 false**，未来重启不再自动进入修复事务。
5. **本轮新的物理 A/B WAL 全量 SHA/RSA 与新账户资金结果的只读验收请求，被执行环境安全检查拦截。** 因此现有证据只证实服务内部 Common 签名提交路径报告成功；不得把后续真实 A/B 认证或完整资金 E2E 记为 PASS。

## 当前必须继续验证
- 在许可执行的环境中以只读方式验新 Trade P246 多出的 SIGNED_FINANCIAL_RESERVE_RECONCILE 帧、原始前 7 帧哈希不变、新账户 after-state 冻结保证金及手续费与 Position 一致，真实 A/B RSA custody 签名相同，并检查现金余额及 MySQL 原入金不变。
- 独立验证真正 Order Pending_Cancel → Trade 释放冻结资金 → Order terminal REMOVE；校验资金、持仓、订单、Projection A/B 一致。此时 Robot 保持禁用。
- MD 原始 Image 实际安装、交易 Web 可见的盘口；真实 Maker/Taker 成交；Robot 多轮连续报价；自动 SIGKILL A/B 主备互切均仍 NO-GO。
- 不能复写旧 WAL、人工覆盖 MySQL 或用单元测试当成真实交易证明。

最终判定：T205 服务报告物理提交成功、但尚未有新的独立双签 WAL 复核；完整交易功能与 HA 仍 NO-GO。
