# T446–T447｜MD QuerySymbol 驱动标记价发布：根因、修复和 Demo 实测（2026-11-02）

## 架构边界（必须保持）

- AdminSvr 的 `querySymbol` 是租户产品启用状态及 `data_source_id → (source_type, source_symbol)` 的权威配置，MD 订阅其完整 Image/变更，无需交易热路径查 DB。
- `BINANCE`：APS 推送币安指数/标记价，MD 依据 QuerySymbol 映射到每个启用产品，即使产品 `security_id` 不等于币安源 `source_symbol` 也必须发布。
- `CUSTOM`：只使用合法的 Broker 自定义价格和原始 TTL；过期即无效，绝不回退币安或旧价格。
- 价格发布仅要求 MD 当前分区为可路由 PRIMARY、Epoch 匹配、控制面正常，**不依赖 Order 盘口 Image/Market READY**。Order 的完整 Image、Snapshot/Diff 连续性及 Market READY 仍仅保护盘口类消息。
- 旧主、非主、RECOVERING 或跨 Epoch 排队的发布必须被隔离；不修改 Trade 的 `5003 MARKPX_NOTEXIST` 风控行为。

## 经证实的故障链

1. 新租户 `DAYWUB` 的产品 `BTCUSDT` 启用，数据库 `data_source_id=binance_btcusdt`，对应 `source_type=BINANCE`、`source_symbol=BTCUSDT`。
2. Trade B 首次查询 Image 能得到有效标记价，但 TTL 到期后返回 `5003`；旧 Trade 镜像 `com.app.dc` 不含租户 Topic 重连过滤器，T445 已替换。
3. 相同 Gateway 只读探针曾在 20 秒收到 Order 完整盘口 Image 2 条、MD 标记价 0 条，排除了“Order 不发布 Image”。
4. MD 源码中 `TradeFacade.publishTenantEffectiveMarkPrice` 与 `MDPublish.Trade` 错误复用了基于完整 Order Image 的 `MdPartitionRuntime.canPublish`，使价格被盘口 READY 门禁拦截。重启 MD 导致盘口 Image 刚好恢复，不是价格的正确前置条件。
5. MD 的旧运行配置没有显式开启 `broker.price.route.enabled`；默认关闭，且 GitHub 的原 `saas-crypto-latest` 缺少已部署的 QuerySymbol 数据源模块。不能只重建旧主分支，否则会丢失功能。

## 代码及部署

- 本地修复分支 `t446-querysymbol-price-independent-20261102` 提交 `f2309b6`，针对 QuerySymbol 源路由、价格/盘口发布分离、同名及别名产品映射、CUSTOM 拒绝币安串源等。
- 以 GitHub `saas-crypto-latest` 原提交 `abb0c4b` 为基底整合缺失源码，统一提交 `13c7b16`，已推送到 `bliplink/com.app.dc.mdsvr:saas-crypto-latest`，提交信息含 `[skip ci]`。
- 本地统一版 Maven `201 tests, 0 failures, 0 errors`；修复来源分支完整 Maven `205 tests, 0 failures, 0 errors`。测试包括 MD 主/副本 Epoch 隔离、无 Order Image 时价源可发布、BINANCE 同名/别名映射、CUSTOM TTL/切源。
- Demo 基于旧 MD 运行镜像，只替换对应的 9 个 class，构建 `local/otc-t446-mdsvr:querysymbol-price`。分别替换为 `otc-t446-mdsvr-b-querysymbol` 和 `otc-t446-mdsvr-a-querysymbol`；旧 `otc-t413-mdsvr-b` / `otc-t413-mdsvr` 已停止但保留用于回退。
- 候选进程 `JAVA_OPTS` 显式启用 `broker.price.route.enabled=true`、`broker.price.receive.enabled=true`、`broker.price.event.publish.enabled=true`。保留原挂载的数据/配置和盘口恢复机制。

## Demo 真实证据

- MD A 的 `DAYWUB/P250` 为 PRIMARY，MD B 为 REPLICA，两个新候选容器运行且无 OOM。
- 独立 Gateway 只读探针连续 20 秒：MD Topic 收到 **23** 条，**23** 条都有有效 MarkPrice，空价 **0**，同期 Order 盘口消息 **7** 条。
- MySQL `dc_tenant_robot`：`DAYWUB` `RUNNING`、活动挂单数 **40**；流动性初始化 `COMPLETE / DONE`、失败次数 **0**。
- 2026-11-02 23:17 +08:00 现场巡检：过去 5 分钟 Order B 发布的 `DAYWUB` 成交 Topic 中 **164 个不同 ExecID**、状态 `Filled`；同窗口所查 Trade B/Order B 日志无新增 `MARKPX_NOTEXIST`，Robot 持续发出 Tape 指令。
- 注意：上述是运行日志与 Gateway/DB 的证据，**不是** Trade A/B 双向真实故障注入、一致性或所有财务 Projection 完整验收通过。

## 尚未通过与下一步

1. 对 `DAYWUB` 的持仓、资金、成交等进行 Common 认证 WAL → Projection/DB 全链路一致性验证（旧 `dc_orders_execorders` 表无本次 E2E 行，不得用来代替 WAL 证明）。
2. 修复 Gateway 在 MD/Trade/Order 物理节点重启后不自动恢复客户端逻辑路由的问题；不能把人工重启 Gateway 作为 HA 验收方式。
3. 验证 MD A/B 自主切换、重连、过期价格拒绝和未就绪盘口隔离；随后 Order A/B、Trade A/B 注入故障并审计水位与真实财务一致性。
4. 后续构建完整候选镜像时，应固定已验证的 Common 3.0.22 和 com.app.dc 依赖，避免回退版本。

**本轮结论：QuerySymbol 驱动的 MD 实时价格、Robot 自动报价和真实撮合成交已得到 Demo 证据；整体集群 HA / 财务完整一致性仍 NO-GO。**
