# T424/T425｜Demo MD 冷市场 Image、Common 认证尾部恢复与真实 Tape 成交（2026-11-02）

## 1. 新租户行情根因与 Order 修复

- 真实现场：APS 持续收到 BTCUSDT 标记价格，Trade B 初始订阅有 MD Image，但新租户 J1P4BK 在首次报价前不具备持续有效的 MD 市场 READY，导致风控 `MARKPX_NOTEXIST (5003)`；重启 MD B 后记录 `MD_MARKET_READY P219/J1P4BK/BTCUSDT`，Trade 改为接受部分 NEWING，Robot 后续进入 RUNNING。
- Order `PublishMarketDept.publishCertifiedPrimaryImages()` 原先忽略 `lastUpdateId<=0` 及买卖盘口均为空的市场。这与“首笔 Maker 需有效标记价”形成启动循环。
- 最小修复：零序号、空买卖盘口也允许生成**认证 Primary** 完整 Image；仅删除这两个空态拒绝条件，保留有名称的市场身份验证、Common Primary 分区证明和 MD 既有发布限制。添加 `PublishMarketDeptEmptyImageTest`，Java 8 编译 + 2/2 JUnit 通过。
- 源码：`.work/ordersvr` 本地提交 `649d6bc`；GitHub `bliplink/com.app.dc.ordersvr` `saas-crypto-latest` 提交 `c59d5103fffa0471bad466008daed679f4f5e2e1`（`[skip ci]`）。本地镜像 `local/otc-t424-ordersvr:empty-market-image` 只叠加 Order 类；与 T423 原 Common JAR SHA 不变 `e7fe2fe5...431ee72`，Trade A/B 继续使用 T423。
- T424 Order B `COMMON_GATEWAY_CERTIFIED_PARTITION_ROUTING_PASS 256`，`Started OrderSvr in 76.876 seconds`；T424 Order A 最终 `PASS 256`，`Started OrderSvr in 91.612 seconds`。这只是启动检查，不表示 HA 故障切换验收已通过。

## 2. Order A P060 真实 WAL 故障与封存恢复

- 新 T424 Order A 首启失败 `Common physically fsynced WAL head mismatch`；**原 T423 Order A** 用同数据重启也一样失败，排除本次 Order 图像补丁造成破坏。
- 用仅添加错误上下文的**隔离临时** Common 诊断镜像 `local/otc-t425-order-a:wal-context` 证实具体分区为 `OrderSvrA P060 E2 Primary`。该诊断类未提交到 Common 或部署为正式镜像。
- 独立只读 Java 物理验证：A 末尾序号 49513，证书 HEAD 49512；B WAL 与证书均为 49512。A/B 至 49512 的完整原始 SHA-256 均与各自可信 custody HEAD 完全一致。A 多余一条**未被证书托管**的 WAL 帧，1,253 字节；认证前缀 97,725,938 字节，原 A 文件 97,727,191 字节。
- 在确认 A 所有业务/诊断容器已退出、B 仍存活之后，执行仅 P060 的受控封存与未认证尾部处理：先完整复制 A 原文件到 Mac `.work/t425-common-wal-context/forensics/evidence/OrderSvrA-P060-E2-seq49513-uncommitted-WAL.full.bin`，fsync 并逐字节 SHA 校验，原文件按文件锁裁去 1,253 字节，fsync，重新与 B 有效认证前缀校验一致。执行结果 `P060_RESTORED_ONLY_ONE_UNCERTIFIED_TAIL_PASS`。
- 没有关闭签名检查，没有清除其它分区、重置 Epoch、创建/伪造签名或删除备份。**这是一项 Demo 临时维护操作，后续仍须统一 Common 自动恢复事务，不能把手工修复算成 HA 自动接管。**
- ZK 抽查 P060 仍显示 A Primary / B Replica E2 READY，即使 A 宕机也未自动重分配，此处属于 **HA NO-GO**。

## 3. Maker/Tape 真实交易和账户证据

- 重启 Gateway 及 Robot 以恢复新的四节点端点注册后，`J1P4BK` 在 MySQL `dc_tenant_robot` 的运行状态达 `RUNNING`，`open_order_count=40`，最后 2026-11-02 10:35 +0800 仍为 40。
- 真实 Robot Tape `tape instruction` 连续发 IOC 买卖（如 Buy 78481.6 × 0.0002 BTC、Sell 78403.1 × 0.0003 BTC）。Order B 的相应 ExecutionReport 明确出现双方 `OrdStatus=Filled`、`ExecType=Trade`，Maker `TimeInForce=PO`、Tape `TimeInForce=IOC`。
- 不依赖 MySQL 旧余额，使用 network=none、只读 Docker volume 的 Java+FastJSON2 解码 Trade A/B **原始 E2 business.wal**，对 `J1P4BK` 的 P238 验证：两节点均有连续 1,226 帧、420 个唯一 `POSTING`，其中 `COMMON_CERTIFIED_CASH_IN=2`、`Trade=418`，没有重复 Posting ID。
- 双节点在 seq1226 的两个账户资金 after-state 完全相同：Maker balance 9999.16398806, usedMargin 4181.90722588, frozenMargin 807.96641000, availableBalance 5008.32430468；Tape balance 9997.49196323, usedMargin 4183.23200802, frozenMargin 86.32583000, availableBalance 5727.88232971。这是**实际成交已写入两份业务 WAL** 的证据，不等于完整自动 HA 压测。

## 4. 未闭环项（不得宣称全量 PASS）

- `HXIAAM` Maker 仍不能进入 RUNNING：现为 `WAITING_MARKET_DATA` 0；此前大量 NEWING 由 Trade 返回 `TRADE_BALANCE_NOT_ENOUGH (5000)`。独立只读签名 WAL 已确认不是没有入金：Maker 余额 9997.92551909、可用 9887.99402765、已用 109.93149144；持有 long .0835 + short .0493 BTC。MySQL 初始化 `dc_users_symbol_config` 杠杆为 1x，代码 `DataFacade.init()` 会加载该配置；若当前运行时有效 1x，含已有仓位的风险名义值约 0.1328×78,000=10,358 USDT，超过可用余额。这是**合理的风控解释，但仍需当前 JVM 精确杠杆/风险计算证明**，不得擅自放松风控或再次入金。
- Projection 曾长期无法追赶：2026-11-02 10:28 左右 `ProjectionSvr.log` 反复报 `SERVER.OrderSvr is not Online partition=P219`。实机 Projection 重启、ZK 服务端点重新注册后，Order P219 水位从 280 推进到 3280，随后 10:35 达到 22780；Trade P238 从 44 追至 1226。MySQL `dc_order_projection_event` 有 STATE_UPSERT/REMOVE/BATCH，`dc_trade_projection_event` P238 1226 条、`dc_trade_projection_mutation` P238 6154 条。
- 旧版 MySQL `dc_orders_execorders` 对 J1P4BK 仍为 0，`dc_users_posting` 仅保留原认证入金两条，`dc_users_balance` 仍显示入金初始 10000，没有投影出真实 Trade after-state。这意味着消费水位和**面向网页/管理查询的读模型**是两项不同验收：后者 **NO-GO**。
- Order P219 投影事件类型只看到 `STATE_UPSERT` / `STATE_REMOVE` / `STATE_BATCH_V1`，没有 `STATE_ATOMIC_MATCH_V1` 与 `STATE_MATCH_SETTLED_V1`；而 `OrderProjectionService` 只有后两种认证配对结算事件才触发填充完整 `dc_orders_execorders`。后续应沿已认证的 Order Match/ACK 事件与 Projection 映射定位，**不编造执行记录、不凭未签名网关消息入账**。
- 尚未执行真实 A/B SIGKILL 双向自动主切与资金、委托、持仓、Snapshot/WAL 自动追平验收；不能宣布 HA PASS。
- 本次没有使用 GitHub Actions，未使用任何未认证自动回退、TLS/HTTP 复制或绕过风险检查的处理方法。

## 下一阶段验收优先级

1. 先补齐签名原始 Match 与 Trade 收据对 Projection 的正式查询视图映射；要求订单成交、成交历史、资金持仓在网页/API 与 E2 签名账本一致。
2. 用合法业务 API 处理 HXIAAM 1x 杠杆下风险占用，或用全新自动审批租户的空账本正式流程验证，不能直接篡改账户余额/签名 WAL。
3. Common 自动消化无证书尾部与自动 A↔B 主备交接（A 停后 B 接管、A 复归追平、逆向交接），由 Demo+Common 机制验证通过后，Order/Trade 按同一 Common 机制复用；最后加 10→50→200 租户负载。
