> **T545 架构纠正（2026-11-07）：本文件中为 ORDER_ONLY 单独新增 `STATE_MATCH_ORDER_ONLY_NOTIFIED_V1`、特殊 ReadModel/回执协议的方案已废弃，不得部署或合并。ORDER_ONLY 必须走现有 `DefaultExecOrder`，与 TRADE 共用成交报文、历史与 MD/K线发布；只在是否调用 TradeSvr 资金/持仓结算上不同。权威纠正文档：`docs/T545_DEFAULT_EXEC_UNIFIED_CORRECTION_20261107.zh-CN.md`。原 T544 业务/行情验收数据可保留，仅架构建议被取代。**

# T544｜ORDER_ONLY 成交通知与交易/K线最终验收边界（2026-11-07）

## 结论：TRADE 业务 PASS；ORDER_ONLY 仍 NO-GO；A/B HA 未复验

当前 Mac fresh Demo 的 Order A/B、Trade A/B、Gateway、MD、Projection、APS 和 Robot 继续运行，没有切换正式业务镜像。本轮只修改验收工具、独立 Order **候选分支**及文档；不改 Common、ZooKeeper、共识/复制/主备机制，不清空现有交易数据。

### 真实持续交易的统一水位

重构 `tests/check_trial_robot_trade_e2_readonly.py`：对 MySQL 多条查询使用 **同一个 READ ONLY REPEATABLE READ 一致快照和固定@ gate_now 时间窗口**，防止实时订单写入时对比不同查询时点而误报 posting_rows 与 event_id 不一致。查询最长超时从 30 秒调整至 90 秒，仍不能因查询超时假称业务 PASS。

本轮真实 10 分钟窗口实测：

- 11 个已自动初始化的租户、11/11 Robot RUNNING，439 笔挂单；
- Order A/B 合计 **1,613 条** Tape IOC Filled，1,613 个不同 ExecID，重复为零；
- Trade 投影 **1,607 个**认证原子撮合事件、**3,214 条**对应 POSTING，每组严格两条，bad_posting_pairs=0；
- 11 个租户余额最近更新，Trade Projection age=0；
- `PASS_LIVE_BUSINESS_NOT_HA`，脚本 8 项单元测试 PASS。**未执行 A/B 双向 SIGKILL。**

修正 `tests/check_demo_full_market_readonly.py` 使其与真正的交易 Web 初次匿名选择产品一致：优先近期真实成交 > LastPrice > 双边盘口，不再误判“启用目录的第一产品”就是首开的 K线图。当前六个既有租户的原有 BTCUSDT 1M/5M/15M/1H、双边盘口、最近成交及 24h 行情 **6/6 PASS**，四个 Web HTTP API 入口可用，九项市场单元测试 PASS。不能因此推断任意无成交的新产品必须产生 K线。

### ORDER_ONLY 缺失的真实根因

独立租户 NRPH66 的 ORDER_ONLY BTC003USDT Maker/Taker 已经各 `Filled`，但 MySQL `dc_orders_execorders` 0 条、MD 最近成交和 K线没有对应数据。根因代码：

- `CrossStrategy.matchOrder` 在开启 Common 认证写入时始终调用 `OrderFacade.commitPreparedExactlyFilledMatch`，提交原子 Maker/Taker WAL；
- 认证撮合中的结果使用 `OrderCertifiedMatchOutbox`，由 `OrderSignedMatchDeliveryWorker` 统一调用 TradeSvr 的 `settleSignedOrderMatch`；直到 Trade 资金结算 RSA 回执和第二次 Order Common WAL ACK 才发布成交给 MD；
- ORDER_ONLY 产品不需要、也不应有 TradeSvr 资金/持仓结算；该模式不能靠 Trade 财务回执释放撮合业务通知。传统 `DefaultExecOrder.Trade` 并不是认证原子撮合最终发布链路，修改旧 DAO 或手工补 SQL 并不能根治。

### 隔离候选分支和具体实现

代码位于 `bliplink/com.app.dc.ordersvr` 的 **`t544-order-only-business-publish-candidate`**，从 `saas-crypto-latest` 创建，未合并正式分支。主要变更：

1. Worker 从 `SymbolRuleFacade.matchingMode(location,securityId)` 严格验证租户产品业务模式；TRADE 保持原签名 Trade 金融结算路径，ORDER_ONLY 绝不发往 TradeSvr；未知模式拒绝。
2. ORDER_ONLY 持有原始 Common WAL 原子撮合的 Maker/Taker after-state、确定性 ExecID 和原始帧 SHA-256；`STATE_MATCH_ORDER_ONLY_NOTIFIED_V1` 是 **Order 业务层**第二次 Common 认证的发布完成记录，Common 自身不知道 ORDER_ONLY/成交类别。
3. `OrderCertifiedMatchOutbox` 与签名帧 codec 支持同一 WAL 前缀/Replica 帧重放，业务发布确认必须关联原始 partition、epoch、seq、matchKey 和 SHA-256，错误来源/伪造摘要直接拒绝，不能误删其他原子成交。
4. 新增 `OrderOnlyCertifiedExecutionReadModel`：从原始 WAL 双订单 after-state恢复完整 ExecOrder，用确定性 `(exec_id,user_id)` 主键以 `REPLACE INTO dc_orders_execorders` 幂等落库。任意一条写入失败都阻止发布后 ACK，重试沿用相同 ExecID 和 WAL 中的成交时间，不向 TradeSvr 写资金/持仓。
5. **实验开关默认关闭**：`order.orderOnly.experimentalPostWalNotification.enabled=false`；只有显式测试环境打开才能运行新的投影→通知→WAL marker 路径。没有覆盖当前运行的 Order A/B。

本机 Java 8 使用现有 Order target/classes、更新后的 Common 已编译类及 Maven 本地依赖进行增量编译：**javac PASS、16 项相关 JUnit PASS**（签名 outbox、恢复、伪造保护、业务模式选择、read model 双行幂等和第二行失败）。**这不是完整 Maven package，也不等于真实双 JVM/新租户实盘验收。**

### 为什么现在不能开启实验开关/替换 Order

新 read model 的 MySQL 投影已经补上，但旧 `PublishOrder.publishCertifiedSettledMatch` 只是将 Maker/Taker report 放入 Gateway 的异步发送队列。**成功入队不表示 MD 已持久化这条成交**：如果随后 `STATE_MATCH_ORDER_ONLY_NOTIFIED_V1` 写入 Common WAL，而节点在 MD 真正接收前崩溃，恢复时 outbox 已被标记为完成，将可能永久漏失最近成交、K线和成交投影。即使 ExecID 是确定性的，也无法凭空补回没收到的消息。

因此默认 **fail-closed**，不能为了让已有脚本 PASS 而在现有 A/B 打开实验开关、假造 MD ACK 或修改 Common 添加业务判断。下一关必须在业务边界实现真正可审计的 **MD 幂等持久接收与回执**，或者等价的已验证持久事件重放方案，再完成以下验收：

- 独立 ORDER_ONLY 新租户：买卖双方 Filled，两个唯一 ExecID 在可信查询/数据库出现，MD 最近成交 + 新5M K线推进；
- Trader 余额/保证金/持仓/资金流水在 ORDER_ONLY 前后严格相等，未调用任何 Trade 财务 RPC；
- 强制注入通知失败/MD 重启/Order A/B SIGKILL 与双向主切，重复/漏发为零，Common 原始 WAL 水位与业务投影一致；
- 满足后把候选合入 Order 的 `saas-crypto-latest`，完成正式 Maven 镜像构建和一键部署，避免又停在只通过单元测试。

当前保留旧 Order/Trade 容器与数据；该候选 **NO-GO FOR PRODUCTION**。不要把 T544 十六项单测冒称完整 Order/Trade HA PASS。