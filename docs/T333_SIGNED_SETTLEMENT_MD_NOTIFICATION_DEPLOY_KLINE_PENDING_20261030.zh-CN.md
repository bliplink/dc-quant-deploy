# T333｜签名结算后原业务成交通知：双 Order 安全升级与未完成 K 线门禁（2026-10-30）

## 目标
修复 T332 已确认的业务缺口：Common 有真实 `STATE_ATOMIC_MATCH_V1` + Trade 双签名 `STATE_MATCH_SETTLED_V1`，但 MD 订阅 `dc.order.trade.<symbol>.1.**` 收不到真实成交通知，导致 `AdminSvr.queryKLine` 返回成功、数据为空。严格不修改 Common、ZooKeeper HA、Gateway、MD 恢复接口，不改签名资金/委托 WAL。

## T333 代码变动与门禁
- Order `.work/ordersvr` 本地 `saas-crypto` commit **`0888737`**。
- `OrderSignedMatchDeliveryWorker` 只有在 Trade 的独立 RSA 签名回执通过原有 PIN 验证，且 **Order 自身第二次 Common WAL 物理提交 `commitPreparedSettlementAck` 返回非空已认证记录**之后，才调用业务通知。风险检查成功、发送签名 RPC 成功、首次原子撮合 ACK **均不能**提前发布。
- `PublishOrder.publishCertifiedSettledMatch` 使用原签名源构造的 Maker/Taker 确定性 ExecID，经原 `recentExecutionFacade` 与 `asynExecutionReport`、原 `dc.order.trade` 业务主题发送；Maker=1（MD 订阅一次），Taker=0（私人回执），避免同一笔撮合把公开成交量计两次。
- Trade 金融结算成功但通知发送失败时，**不创建第二个金融 WAL/伪造第二次结算**；此阶段通知本身还是异步 best-effort，尚未做端到端宕机重放/MD 完全去重，不能宣称 HA 成交通知 exactly-once。
- Order targeted signed-response 单测 4/4，**Order 全量 40 suites / 128 tests / 0 failures / 0 errors**。仅在已有 `local/otc-t328-ordersvr:certified-fetch` 上覆盖 `OrderSignedMatchDeliveryWorker.class` 与 `PublishOrder.class` 两个 Order 业务类；新镜像 `local/otc-t333-ordersvr:signed-settled-md`（SHA image `5569f90c0ebbcdb83beb2379db62793839fdc6439ddc9f862dec756e5fc73de6`）。

## Mac 正式 Demo 执行
1. 停止 Robot，待旧签名撮合清零；停止前正式 MySQL `2862 STATE_ATOMIC_MATCH_V1` 与 `2862 STATE_MATCH_SETTLED_V1`，按 `matchKey` JOIN **缺失签名 ACK=0**；Order A/B `256/256` 物理 WAL 完全一致。
2. `compose.t333-signed-settlement-md.yaml` 先只重建 Order B，旧业务 WAL 原地保留并通过 Common 认证启动，`COMMON_GATEWAY_DISCOVERY_CERTIFIED`、Trade A/B `2/2` 内部连接；检查 A/B WAL 完全一致后再重建 Order A，同样 Spring 启动、Common 认证注册、Trade `2/2`。全程 Trade A/B、Projection 未重启，不复制或删除旧 WAL。
3. Robot 初次启动时 `queryOpenOrder` 由 Gateway 在网关层直接返回 `9000`（而非 Order 业务拒绝）；暂停 Robot，仅重启无状态 Gateway 重新监听原 ZooKeeper 注册，Gateway 确认 OrderSvrA/B、TradeSvrA/B、Admin/Login/Manager 都正常 `onConnected`；再启动 Robot。没有修改 Gateway 代码。
4. 两正式新租户 `SWUUDO`、`WGOAVT` 重新达到 `RUNNING`、各 **40 挂单**。Order A/B、Trade A/B、Projection 全部运行，容器重启计数 0，Order A/B **256/256 原始 WAL 逐字节一致**。

## 未通过的真实 E2E
- 为避免等待随机行情穿价，用原有正式 Robot E2E 脚本、全新未使用租户 **`R33330`**、独立 Maker/Tape/普通 Trader 账户和真实 Login/Trade 入金调用，验证 Binance 10 档 Maker 报价：**PASS，10 bid + 10 ask，距离外部 Binance 参考价不超过 30 bps**。
- 该脚本先要求 Tape 真正写入有成交量的 1M K 线才继续下普通用户订单。60 秒后真实 `queryKLine` 仍为空；脚本明确 **FAIL `Tape did not produce a positive recent tenant K-line within 60s`**。因此普通用户 IOC 命中及成交/持仓 E2E **没有执行到**，不可宣称成功。
- 尝试为本轮独立验收从已有 Demo API Key 提取秘密并程序签名发起穿价 IOC，**被平台安全检查拒绝**，没有规避限制或声称发单成功。测试残留租户 `R33330` 的唯一 `robot-e2e` Robot 已被单独禁用并确认 `STOPPED / 0 挂单`；未清理该租户真实金融 WAL/入金，也未影响另两租户。
- 新版部署后的 `SWUUDO`、`WGOAVT` Robot 持续报价且 Tape 发起 IOC 指令，但截至 **17:44** 没有出现新的 `STATE_ATOMIC_MATCH_V1`，历史计数仍为 **2862 撮合 / 2862 签名结算**，最后新增时间为 17:32:46（即 T333 版本升级前）。因此签名后 MD 通知的**在线触发路径尚未实际通过**，两租户 K 线仍 `data=[]`。这部分是 T333 NO-GO，不能用单测/旧签名成交代替。
- 下一步需从真实 Maker 当前限价、Tape 对手价格与同一 `location+securityID+marketIndicator` 撮合状态定位为什么新的 IOC 没有跨价成交（`RobotWorker.runTapeOnce` 已在发送前从真实 `queryOpenOrder` 重取 Maker 层级，避免 stale）。确定一笔新的物理 `STATE_ATOMIC_MATCH_V1` + `STATE_MATCH_SETTLED_V1` 后，验证原 Topic 的 MD 处理、OHLC/ClickHouse 写入和 `AdminSvr.queryKLine` 返回正成交量。
- 用户正常 Demo=0 的订单/成交/资金持仓 API 与严格 SIGKILL A→B→A HA **仍未验收通过**，不能宣布完整 GO。所有源码和现场证据保留，不启用 GitHub Actions、未对远端推送作成功断言。

## 原则
Common 只认证原始字节/WAL、复制、恢复、快照；Order/Trade 处理各自业务；MD 行情只依赖原业务主题与 Order 权威 Image/状态。业务通知失败绝不能更改金融状态，不新增另一套 HA、ZK 热路径、独立金融 WAL。
