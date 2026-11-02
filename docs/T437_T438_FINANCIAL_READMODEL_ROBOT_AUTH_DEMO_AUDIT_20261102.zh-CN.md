# T437–T438｜Trade 财务投影与 Robot 认证恢复实机审计（2026-11-02）

## 项目目标和边界

- 目标：维护 Demo 上新租户自动审批→Maker 双边报价→Tape 真实撮合→Trade 认证余额/持仓→Web 与历史查询一致→Order/Trade A/B 自动安全主切。
- Common 统一持久化/快照/授权/WAL，业务服务不另行实现集群逻辑。验证环境数据为开发 Demo，但不能静默重复入金、伪造历史成交或跳过风险授权。
- 统一工作分支：`saas-crypto-latest`；本地编译 Docker，GitHub Actions 不启用。

## T436 已完成的实际前提

- Trade A/B 均部署 `local/otc-t436-tradesvr:certified-margin-collateral`，23/23 定向测试，仍使用未变更 Common Jar。
- Order A/B 认证路由 256/256，各自 Trade A/B TCP 连接 2/2；已验证 Order A/B 认证 WAL 无分叉和未确认尾部。
- 16:31 后 JRHHXA/KCV203 Maker 新单返回 `success:true, code:0`，Order 两租户均发布真实 `Trade/Filled` 与不重复 ExecID；MD B 重连后 ClickHouse 新成交恢复写入。
- Trade 修复 GitHub：`bliplink/com.app.dc.tradesvr` `saas-crypto-latest` commit `7fd9b3e4deca4e121b8994de174b8033d40fd809`。

## T437：根因、完成与未通过

**经运行镜像字节码及实际 MySQL 确认：** TradeProjectionService 只做签名事件归档、`dc_trade_projection_mutation` 和 `dc_trade_projection_watermark` 更新，**没有**把 ACCOUNT_BALANCE / POSITION 物化进 `dc_users_balance`、`dc_orders_position`。这不是未写认证 WAL，也不是重启 MySQL 能修复。

- 18:00 前后财务事件有约 12,892 条账户 Mutation 和 12,884 条持仓 Mutation，投影水位在 P129/P238/P240/P242；四个 JRHHXA/KCV203 账户 MySQL 余额仍全部 10,000、used/freezed margin 为 0，明显滞后。
- 编写 `CertifiedTradeFinancialReadModel.java`：从已提交的 Trade 投影 Mutation/Watermark 读取，只按 `location + user_id`、`location + user_id + security_id` 更新 MySQL 只读业务表。按分区以最多 256 seq 为一批，SQL 事务同时提交变更与 `dc_trade_financial_readmodel_cursor`；跨 Epoch 不具备可信证明时拒绝继续，不跳过旧水位。
- 9/9 JUnit 定向测试 PASS。Docker `local/otc-t437-projectionsvr:financial-readmodel-disabled` 已本地构建，3 个业务 class 与输出哈希匹配。源码：`bliplink/com.app.dc.projectionsvr` `saas-crypto-latest` commit `e25024163fbcdbcd475ee08d4cc8eeb2df5a34c9`。
- **关键门禁：** 对独立 MySQL 临时表执行兼容性测试时被执行环境安全检查拦截。因此 T437 的物化开关 **默认关闭**，**没有替换/开启线上 Projection，也没有写入财务业务表**。仅完成编译、9 测试、镜像、GitHub 源码；真实数据库补录仍 NO-GO。不得声称完成资金持仓 E2E。
- `POSTING` 资金流水和执行历史表仍需单独核实；T437 本轮只处理 ACCOUNT_BALANCE 与 POSITION，不应声称全财务读模型完成。

## T438：Robot 认证过期导致退化

- 17:59 实机：JRHHXA `DEGRADED/0`，最近错误 `gateway rejected placeOrder: authenticated user session is required`；KCV203 `RUNNING/40`，但最近成交已停在 16:52。
- Root cause：`OrderSvr.SessionOrderAuthority.scope()` 在 Common WAL 提交**之前**明确返回 code=1004/精确错误 `authenticated user session is required`；`RobotSvr.TradingGatewayClient.requestAs()` 收到此错误会刷新 Trader API TCP 会话，但对所有写请求一律禁止重放，导致明示未提交的订单也进入 Robot DEGRADED。
- 修复仅对 `OrderSvr.placeOrder/cancelOrder/cancelBatchOrder` 且 **code=1004 + 完全匹配消息** 的确定性 WAL 前拒绝，刷新认证后用同一原始内容和 clOrdID 再请求一次。**空响应、网络超时、Gateway 9000、资金请求及不确定写入仍严禁自动重试。**
- 19/19 JUnit 定向回归 PASS；`local/otc-t438-robotsvr:prewal-auth-refresh` 6 个运行时 class 哈希验证 PASS；18:15:55 使用原环境/挂载配置替换运行 `otc-t438-robotsvr-session-recovery`。源码：`bliplink/com.app.dc.robotsvr` 新建 `saas-crypto-latest` branch commit `d55512c80679b04170d142658d2ffe6b632b499d`（该仓原本没有该分支，本次从远端 `saas-crypto` 创建，未把本地其它 dirty 文件混入提交）。
- 18:16：JRHHXA 真实 `DEGRADED → RUNNING/40`，ClickHouse 成交 367→369；18:18:49 累计 376，最后成交 18:16:59。**这证实部署重启的业务恢复，不构成一次真实服务端凭据到期再自动续认的完整验收。**

## 18:19 仍未通过的实际业务项

- JRHHXA DB `RUNNING/40`、KCV203 `WAITING_MARKET_DATA/0`，两租户 Robot 实际开放查询约 39 条。
- 18:15 后归档订单投影：JRHHXA 18 条 Filled、39 条 New、44 条 Rejected；KCV203 39 条 New、65 条 Rejected。
- Rejected：KCV203 45×`5000 TRADE_BALANCE_NOT_ENOUGH`、20×`5003 MARKPX_NOTEXIST`；JRHHXA 30×5000、14×5003。必须分别验证 Common 认证账户实时可用额度与 APS→MD→Trade 新鲜标记价格；不直接调大余额或关闭风险校验。
- HA 自动 A/B 主切（含故障下无重复/无丢失、Epoch 撤权与安全归队）**未完成验收**。
- 18:18 Mac 数据盘约 54% 使用，仍有约 65 GiB 空间。

## 下一步严格门禁

1. 针对两个租户已认证的最新 Trade 账户/委托冻结状态解释 5000；核实 Mark Price 的 TTL、更新时间、订阅断线重建与拒绝触发链路解释 5003。保证 Robot 真实订单数而非只看 DB 的 `RUNNING/40`。
2. T437 SQL 兼容性需获得正常允许的隔离数据库级测试，再开启开关，小批量验收 MySQL 余额/持仓与 Common 认证 WAL 的精确一致性；此前财务业务表保持原样。
3. T438 下次自然会话到期做真实重认验收，记录同一幂等键没有重复订单。
4. 所有业务 E2E 稳定后才进行 Common 自动 Order/Trade A/B 故障注入与一致性终验。

## T439｜后续源码复核：5003 订阅／缓存判定（尚非实机根因）

> 2026-11-02 后续 GitHub 静态复核。以下只证明源码行为，**没有**取得新的 Demo 运行日志或重新部署证据；不可把待复现的机制等同于已确认故障根因。

1. **Trade 的 5003 判定**：`com.app.dc.tradesvr/src/main/java/com/app/dc/service/check/MarkPxCheck.java` 的 `Newing + OPEN` 调用 `MarketPriceFacade.getMarketPrice(location, securityID)`，返回 null 即 `MARKPX_NOTEXIST`。不应通过 `allowMissingMarkPrice=true` 绕过风险校验。
2. **5 秒新鲜度门禁**：`com.app.dc.tradesvr/src/main/java/com/app/dc/service/price/MarketPriceFacade.java` 默认 `risk.mark-price.max-age-ms=5000`，基于接收本地时间 `markUpdatedAt` 判断过期。实时诊断应逐租户、逐 Symbol 记录 MD 发布时刻、Trade 接收时刻、缓存更新时间与 TTL，不能仅凭最新成交价存在认定标记价有效。
3. **明确需要排查的两条条件分支**：
   - `MarketPriceFacade` 的 MD 回调将 `t.getMarkPrice()` 解析失败／字段为空时的 `markPx=null` 写入缓存并将 `markUpdatedAt` 清零。需要用实际 MD Topic 消息证明有无“只有成交价、没有标记价”的输入；如有，核实其是否造成 5003，且不能把超过 TTL 的旧标记价无限保活。
   - `getMPrice()` 使用 `subscribedMarkets.add(key)` 一次性触发订阅；订阅抛异常时仍保留订阅标记，源码依赖 Common MD 订阅层完成恢复。需查失败日志及下游恢复事实；不能未经证据就在下单热路径增加 Image 轮询。
4. **MD 发布端**：`com.app.dc.mdsvr/src/main/java/com/app/dc/service/index/IndexFacade.java` 调用 `TradeFacade.publishTenantMarkPrice`，后者对 `htLatestTrade` 中已有的对应租户／Symbol 发送更新；要核对发生 5003 的租户是否有缓存市场、源字段不为空、实际 Topic 推送与 Trade 订阅是否匹配。
5. **T437 不得提前开启**：新 `CertifiedTradeFinancialReadModel` 的 9 项测试只覆盖 Mutation 字段校验，不涉及真实 MySQL 方言、主键、事务回滚或 Epoch 切换。开启前必须以独立 MySQL 临时表验证 `dc_users_balance` / `dc_orders_position` Upsert、游标原子提交及恢复后重放，并验证当前 Epoch 之前的初始化状态是否完整可重建；不得凭解析单测直接生产回填。
6. **5000 需要真实 Trade 帐户快照对账**：对每个 Maker 账户记录 `balance / usedMargin / freezedMargin / freezedCommission` 和实际订单风险需求，以 Common 认证状态为准。T437 测试里的数值是模拟样例，不作为当前实机账户余额证据；不得通过重复入金、清除委托或放宽风险绕过。

**下一步实际执行门禁**：先导出 5003 发生前后相同 `location + security_id` 的 APS/MD 发送与 Trade 接收日志、`markUpdatedAt` 差值，同时核对 Trade 账户快照解释 5000。确认具体触发分支后才允许定向修复；之后恢复双租户持续报价／Tape 成交，完成 T437 MySQL 兼容验收及 A/B HA 故障注入。当前所有 NO-GO 结论不变。


## T440｜2026-11-02 18:53 Demo 财务物化实际部署验证

### 从原单机路径到 Common 集群路径的根因判定

- **已确认回归（T437）**：认证 Trade WAL → `dc_trade_projection_mutation`/`watermark` 事务归档没有继续物化至 `dc_users_balance`/`dc_orders_position`。这是从旧业务表写入路径切到 Common 认证状态后遗漏的查询侧适配；不是认证 WAL 或 MySQL 本身丢失。修复使用已经在 `com.app.dc.projectionsvr/saas-crypto-latest` 提交的 `CertifiedTradeFinancialReadModel`，Common 无业务代码修改。
- **保证金（5000）的实机依据**：18:40 前后的认证余额快照，JRHHXA 001 balance=9998.16819655 / used=9163.67978515 / available=834.47513741；KCV203 001 balance=9998.16323518 / used=9189.18789481 / frozen=803.1374 / available=4.84054341。审计拒单发生在前一时间窗口，**仍需对齐拒单前精确财务水位**，不可用较晚解除冻结后的余额替代。两租户 BTCUSDT Maker 多空总仓高：JRHHXA 001 long=0.0673 / short=0.0496，KCV203 001 long=0.0603 / short=0.0571；Robot 配置是单侧 20 档、depth_margin_budget=1000、max_position_qty=0.1、`inventory_auto_reduce_enabled` 未配置（代码默认 false），而 Robot `netPosition` 读取 Trade 认证持仓后使用 long-short 净额。**由多空总保证金和净头寸控制口径不同造成持续资金压力，是已证实的配置/机制失配；每一笔 5000 仍需按事发时点风控快照核对**，不能关闭严格保证金，也不得重复入金。
- **标记价（5003）仍待动态链路证明**：旧版 Trade `MarketPriceFacade`（2026-09-04 `bdbd5e9`）已经使用 5 秒风险 TTL，也已对空 MarkPrice 清缓存。新版本的重大变化是 `getMPrice` 改为非阻塞单次订阅（`subscribedMarkets.add`）且异常时保留该标记，依赖 Common 订阅层自动重新连接。须核对 APS→MD 缓存→租户 Topic→Trade 回调的真实帧/时序，才可定性 5003；严禁恢复每笔下单轮询 Image 或使用 LastPrice 绕过。

### 可复核的 T440 实机测试与操作

- Demo 主机：Mac Docker，数据源 `otc-t398-mysql`，数据库 `dc`。正式财务表操作前用 MySQL 8 的 **TEMPORARY** 克隆表模拟原始列及 UPSERT；balance、position、cursor 同事务 `ROLLBACK` 后分别为 0 行，COMMIT 后分别为 1 行，DECIMAL(30,16) 数值精确保持；未写正式四账户。
- 完整性预检：Epoch2 `ACCOUNT_BALANCE` 13,249 条，`POSITION` 13,241 条；两类 `JSON_VALID=0` 计数均 0，必要字段缺失计数均 0。JRHHXA/KCV203 的四个账户在 Epoch2 都有变更。
- 将旧运行容器 `otc-t434-projection-class-parity` **停止但保留**，复制原服务网络/挂载/运行环境配置并启动 `otc-t440-projection-financial-readmodel`，镜像为 `local/otc-t437-projectionsvr:financial-readmodel-disabled`（镜像 SHA256 前缀 `56fe3bb0a2c0d57c638`），以 JVM `-Dtrade.financial.readmodel.enabled=true` 激活已提交的新类。**没有替换或编辑 Common/Order/Trade 的认证 WAL。**
- 18:53:26 启动日志 `CERTIFIED_TRADE_FINANCIAL_READMODEL_STARTED`；18:53:28–31 四分区 `CAUGHT_UP`：`P129 epoch2 seq2523`、`P238 epoch2 seq3348`、`P240 epoch2 seq2679`、`P242 epoch2 seq2765`。真实 MySQL `dc_trade_financial_readmodel_cursor` 对应四分区与 `dc_trade_projection_watermark` **4/4 MATCH**。
- 实际正式业务表当前已写回四账户余额/已用与冻结保证金及四个 BTCUSDT 持仓，值与上述认证 Mutation 最新快照一致；`dc_orders_position` 初始空表已变为 4 条实际头寸。写入的是读模型，非新增资金、订单或 Trade WAL。
- **尚未通过/待检**：按重启重复消费严格验证不重复、POSTING 流水读模型、Robot 持续运行/成交、5003 实帧定位、5000 拒单前精确水位与 A/B 自动互切都未完成；不得宣布整体 GO。Robot 容器在本轮曾有退出 137（`OOMKilled=false`）及后续人为终止 143，不能以数据库旧 `RUNNING` 字段代替真实运行状态。财务回填成功也不代表 HA 完成。


### T440 18:57 重启幂等与 18:59 只读 MD 抽样

- 18:57:35 实际 `docker restart` 新 Projection；18:58:23 日志检测 `CERTIFIED_TRADE_FINANCIAL_READMODEL_STARTED` PASS，未见 `CERTIFIED_TRADE_FINANCIAL_READMODEL_RETRY`。
- 对 JRHHXA/KCV203 四个余额／四个持仓在重启前后进行一致算法的 MySQL MD5：余额 `f0c38965d1575a2d64492056a3ae604c`，持仓 `4c1fa99fc119787184292355529e070c`，前后**完全相同**，记录数均 4；P129/P238/P240/P242 与 Trade 源水位 **4/4 MATCH**。T437 余额/持仓认证读模型、事务提交与重启幂等可标记**Demo 范围 PASS**，POSTING/资金明细仍未覆盖。
- 18:59:38–47 从本机 Gateway 的公开 `MDSvr.queryPublicMarket(location,BTCUSDT)` 做两租户各五次**纯读取**：所有返回 `code=0`，都有非空 MarkPrice/IndexPrice，且 18:59:38→42 有实际变化，两租户标记价同步；这证明抽样时 **MD 公开行情有标记价**，不能直接认定 APS 或 MD 全局停供。18:58 左右单次公开盘口查询 JRHHXA `bookLevels=0`、KCV203 `bookLevels=13`，当时 Robot 未运行，不能视为 40 档持续报价通过。Trade 本地 mark 缓存/订阅恢复仍需对时观察，5003 尚未确证修复。


### T441｜5000 已确认的 HEDGE/Robot 风险口径失配

- Demo MySQL `dc_users_config` 确认 JRHHXA/KCV203 的四个 Maker/Tape 账户均使用 `position_way_type=HEDGE`，Symbol 1x 杠杆。认证 WAL 投影中的真实多/空仓位都非零，例如 JRHHXA Maker001 long 0.0673 + short 0.0496 = **gross 0.1169 BTC**，但 net 0.0177 BTC；KCV203 Maker001 gross 0.1174 BTC，net 0.0032 BTC。两账户已用保证金分别约 9163.68 和 9189.19 USDT。
- `RobotRepository.netPosition` 只解析 TradeSvr `PositionReport` 的 `longPosition-shortPosition`，再与 Tape 净值相加。`QuoteEngine.build(...,netPosition)`/ `InventoryController.allowBid/allowAsk` 的硬限只比较**净**偏差与 `max_position_qty=0.1`，不检查 HEDGE 多+空总占资；`InventoryController.reduce` 也只看净偏差，且当前 `strategy_config` 没有 `inventory_auto_reduce_enabled`，默认 false。
- **具体失配**：Robot 在净头寸远低于 0.1 的情况下继续补买卖报价；Trade 新认证入场按真实 `usedMargin+frozenMargin+commission` 拒绝无足额抵押的 OPEN，产生 `5000`。这种差异在迁移到 Common 认证财务状态、严格校验后暴露。此处不得恢复旧的不充分校验或绕过 5000；要在 Robot 使用**权威 Trade Balance/Position** 对 HEDGE 总仓和当前可用保证金进行报价/减仓联动，且 Tape 也不得无约束地累积双向 gross。**本轮只完成取证，尚未部署该 Robot 机制修复。**
- 进一步需把每笔 5000 对齐拒单前 Trade 帐户序号/冻结状态，尤其 JRHHXA 拒单后取消旧委托恢复了部分可用余额；不能仅用取消后的 `availableBalance` 反证拒单。
- 只读 MD 查询在 18:59 多次返回两租户同步、变化的 MarkPrice，说明当时的 APS→MD 对外公开价格可用；5003 需观察每个 Trade 节点的订阅接收时间与本地 TTL。这是**未闭环项目**，不能宣布已经修复。
