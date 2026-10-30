# T332｜原始 Common WAL→Projection 批量回放与真实双租户签名撮合验收（2026-10-30）

## 目标与执行范围

直接在 Mac Demo 的 T330 新环境修复真实 Order Projection，保持现有 Order/Trade A/B、Gateway、Robot 不重启、不清空任何 Common WAL。严格复用 Common 物理 CommitIndex/签名读取；Common 不能识别 IOC、GTC、持仓或行情，业务事件的解释留在 Order/Projection。

## 原始故障（实测）

- T330 新租户 SWUUDO / WGOAVT 自动审批、Maker/Tape 各实入金 10,000 USDT、每租户 Robot 40 挂单/运行正常。
- 运行中的 ProjectionSvr 反复报 `projection event exists ahead of watermark`，Order 事件表和水位均为 0。
- Order 经认证的原始 WAL `eventId` 是**业务订单 ID**，同一订单有多次状态变化；MySQL `dc_order_projection_event.event_id` 为主键，重复业务 ID 使同一事务回滚。
- 业务 Order 此后也会提交 `STATE_BATCH_V1`、`STATE_ATOMIC_MATCH_V1` 和签名结算回执 `STATE_MATCH_SETTLED_V1`；旧 Projection 只处理 `payload.order` 单次状态。必须在**投影端**按真实业务帧展开，不能篡改 signed WAL。

## T332 修复及测试（已完成）

- Projection repo `.work/projectionsvr` `saas-crypto` 本地提交 **`6005498`**，新增/修复 `src/main/java/com/app/dc/projection/OrderProjectionService.java`，新增 `src/test/java/com/app/dc/projection/OrderProjectionBusinessFrameTest.java`。
- 使用不可变 Common WAL `partition:epoch:seq` 作为**唯一投影事件键**，物理 WAL 原字节完全不改，确保每物理序号只推进一次 MySQL 水位。
- `STATE_BATCH_V1`、`STATE_ATOMIC_MATCH_V1` 内的全部 after-image 在同一 DB 事务更新，并且只在成功后推进一次水位；`STATE_MATCH_SETTLED_V1` 仅认证记录并推进水位，不虚构订单。未知、损坏的帧拒绝，不允许跳过。
- Projection 离线 Maven **25 tests / 0 failures / 0 errors**，其中新批量/回执/重复 ID 测试 4/4；额外从**当前运行容器拷贝精确 105 MiB 的依赖集和 classes**以 Java 8 编译、运行新 JUnit **4/4 PASS**，防止本地 m2 的同版本 Jar ABI 不一致。
- 仅重建单服务 Overlay 镜像 `local/otc-t332-projectionsvr:certified-batch`，基于 `local/otc-t252-projectionsvr:installed-image` 仅替换 `OrderProjectionService*.class`。正式 Demo `dc-saas-projectionsvr` 已通过 `compose.t332-projection-only.yaml` 单独替换，内部新 class SHA256 `70d1cf40b32a7e964a0243783d2cca3ab7b264ec9629ff121973d2fed7cf3dc2`。
- **没有重启 Order A/B、Trade A/B、Robot**，其启动时间不变、RestartCount=0。

## 真实 E2E 结果（使用新 MySQL，非模拟）

- T332 投影从 `event=0,watermark=0` 实际推进到 **8,000** 条事件和两个有效水位：P094 Epoch2 Seq4500、P193 Epoch2 Seq3500；继续正常消费，无之前的重复 `eventId` 拒绝。
- 16:58 的正式 MySQL JOIN：`STATE_ATOMIC_MATCH_V1` **1603 条**，`STATE_MATCH_SETTLED_V1` **1603 条**；使用业务 `matchKey` 一对一关联，**1603/1603** 找到签名结算回执；按租户 `SWUUDO=625`、`WGOAVT=978`。`dc_trade_projection_event` 同期 **5082 条**。
- 之后再次抽查 1701 笔原子撮合和 1701 笔签名回执，两个租户各自 Robot `RUNNING`、40 挂单。Order A/B 的**256/256 物理原始 WAL 完整字节相同**，Order/Trade A/B、Projection 均运行且重启数 0。
- 按配置 `projection.saveDemo=false`，内部 Robot Demo=1 订单历史 `dc_orders` / `dc_orders_execorders` 不落常规用户数据库，这是**有意配置**，不等于没有真实签名撮合/资金结算。此前 `ORDER_PERF_STATS.tradeExecs=0` 不是 Common 签名撮合 Outbox 的权威统计，不能再用来否定 WAL+Trade 签名双证明。

## 尚未通过/待修

- 两租户正式 Gateway `MDSvr:queryPublicMarket` 返回 `code=0`，但 `AdminSvr:queryKLine` 返回 `code=0,data=[]`；K 线/24h/成交量**未验收**。MDSvr 匿名 Kline 返回 `AUTHENTICATED_SESSION_REQUIRED`，符合现有认证要求。
- 代码核查发现 `OrderStateJournal.commitPreparedAtomicMatch` 在 Common ACK 后仅 apply 订单簿及记录 MatchOutbox；`commitPreparedSettlementAck` 在真正签名 Trade 回执后只标记完成，不调用旧的 `PublishOrder.OnTrade(ExecOrder)`；而 MD `ExecOrderInput` 订阅 `dc.order.trade.*.1.**`。**这是当前 K 线缺失的高概率业务事件发布缺口**，需要用确定性 ExecID、签名 ACK 驱动恢复安全的业务通知，不改 Common/旧 Gateway。未证实 ClickHouse 实际写入：执行端直接 ClickHouse 检查被安全门禁拦截，不能虚构结果。
- `dc_orders` 中 Demo=1 为 0 是配置预期；还需要以真实普通用户 Demo=0 下单成交，核对订单、成交、资金、持仓、MySQL 和 API 查询。
- **严格自动 Order/Trade A→B→A SIGKILL 故障恢复未开展，本轮仍为 HA NO-GO**。不得用已通过交易/证书证明替代故障注入，亦不得把 T329 物理 ACK 失败尾部冒充已提交。
- 本地已提交：Order T331 `9761518`、Projection T332 `6005498`、部署 T330 `c3e5c4c`。均未使用 GitHub Actions；本轮无远端 push 断言。

## 后续执行边界

首要恢复签名已结算业务事件到 MD/行情/ClickHouse，验证 Kline > 0、用户普通成交及资产一致性，再进入自动 HA 注入。保留 T329 原 WAL 失败证据和整个 T330/T332 已认证运行数据；仅使用正式业务事件发送路径，不允许模拟成交、假 ACK、假 READY。
