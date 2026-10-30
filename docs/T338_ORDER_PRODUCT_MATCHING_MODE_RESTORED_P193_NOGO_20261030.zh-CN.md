# T338｜恢复 Order 产品级 TRADE / ORDER_ONLY 路由，不掩盖 P193 Common NO-GO（2026-10-30）

## 实际发现

- 当前 T335 Order A/B Docker 镜像均有 `DefaultExecOrder.class` 和 `TradeExecOrder.class`，但**没有** 10 月 20 日已交付的 `ProductMatchingExecOrder.class`。
- 运行配置 `execOrderType=trade` 属于**进程级**旧执行器选择；无法正确支持同一 OrderSvr 实例中不同租户、不同产品分别选择 `TRADE` 和 `ORDER_ONLY`。
- Admin 源码仍有 `matching_mode` 产品存储以及 `querySymbol` 的完整 `tenant_matching_modes` 信息；丢失的是 Order 端的模式消费/选择接线，不是需要发明一种新产品。
- **这个代码回退不等于 P193 的 WAL 根因。** P193 是 Common 认证 CommitIndex 22667 与物理 WAL 22668 不一致；仍必须先按已认证签名边界恢复，不可借业务模式配置解除。

## 当前已完成（本地源码）

- 在 `bliplink/com.app.dc.ordersvr` 本地 `saas-crypto` 恢复原 `3f38bf9` 的产品级路由，由 `location + security_id` 选择：
  - `TRADE` → 现有 `TradeExecOrder`（资金冻结、持仓/结算）。
  - `ORDER_ONLY` → 现有 `DefaultExecOrder`（只做 Order 委托、撮合、成交回报，不通过 Trade 更新资金/持仓）。
- 原业务执行器不再以进程级 `execOrderType` 条件互斥实例化，由 `@Primary ProductMatchingExecOrder` 统一选择；同批次混合结算模式拒绝。
- Order 的 `SymbolRuleFacade` 解析 Admin 全量 `tenant_matching_modes`（包括已停用产品的历史模式），拒绝未知/非法值；不依靠全局默认替代未加载的产品结算模式。
- 没有触碰 Common、Gateway、Trade，也没有修改最近 T335 的部分成交、已签名撤单和恢复逻辑。
- **Order Maven 全量：41 suites / 132 tests / 0 failures / 0 errors / 0 skipped。** 原 T335 为 130 tests，本次增加 2 项模式回归。Git `diff --check` PASS。本地提交 `310e46f`。

## NO-GO 和验收门禁

- 这仅是 Order **源码恢复与单元测试通过**，没有重新构建/替换正在运行的 Order A/B 镜像，产品级实时 ORDER_ONLY 仍未在 T338 验证。
- Common P193 正式在线未认证尾部恢复、自动旧主隔离/Watch、自动重加入及 A↔B 故障切换 **尚未完成**。Common 的 T337 原始 RSA/Custody 认证及 22667 条已提交回放见 `T337_P193_T336_WAL_ROOT_AUDIT_RECOVERY_NOGO_20261030.zh-CN.md`。
- 后续严格按已有架构门禁：先 Common P0 自动恢复/切换，再同一 Common JAR 的 Order/Trade 集成，然后 fresh tenant → ORDER_ONLY 纯撮合不改资金 / TRADE 部分成交撤单原杠杆释放 / Robot Tape MD Projection E2E；不得用单测或容器 UP 宣告正式交易 HA GO。
