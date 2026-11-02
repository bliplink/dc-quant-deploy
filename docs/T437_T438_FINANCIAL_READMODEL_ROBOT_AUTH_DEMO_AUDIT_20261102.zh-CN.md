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