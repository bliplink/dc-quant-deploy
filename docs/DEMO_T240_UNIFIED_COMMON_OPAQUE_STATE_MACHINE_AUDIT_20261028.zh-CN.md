# T240｜Order/Trade 回归单一 Common 状态机提交边界

验收时间：2026-10-28，Mac Docker Demo，`saas-crypto`。本次只进行源码修改、本地编译、单元测试、审计记录，不改变现有运行中的 Order/Trade Docker 镜像，不触碰用户数据。

## 架构边界

- **Common** 已有的 `CertifiedBusinessCommandRegistry.commitThenApply(partition,encode,apply)` 接受不透明 WAL `byte[]`：分区、epoch、sequence、物理双持久化、RSA/Custody、主备授权、Snapshot/Replay 归 Common。无需让 Common 识别 IOC、FOK、余额、仓位、杠杆等字段，也无需修改 Common。
- **Order** 自己决定所有订单类型的撮合、账户事件，准备完订单簿和成交状态再交给同一套 Common 提交；不能先改内存。跨 Order/Trade 认证结算 Saga 是业务级投递问题，不在 Common 增设订单类型判断。
- **Trade** 负责金额、持仓、冻结、手续费、流水及设置的业务合法性，聚合完整 `TradeStateBatch` 调用同一个 `TradeStateCoordinator.commitPreparedState`。Common 一律存字节。Trade 的域校验（跨租户/风险/来源经济权益）继续保留，这不是 Common 的限制。

## 已落地代码

### Order
1. 新增 `OrderPreparedStateBatch`：`STATE_BATCH_V1`；一条同租户、同市场、同产品的 Common WAL 事务可含多项有序 `UPSERT/REMOVE` 状态，单次持久化/复制，拒绝重复 orderId、跨书本及 lastUpdateId 跳号。参数 JSON 封存，原对象后续修改不影响已准备事务。
2. `OrderStateJournal.commitPreparedBatch`：Common `commitThenApply` 一次提交、精确解码原始 WAL、认证 ACK 后才应用；禁止绕开已有 Match Outbox 把 Filled 当成普通无结算事件的状态直接确认。现存 `commitPreparedState` 和 `commitPreparedAtomicMatch` 留作兼容，不再开发业务类型专用 WAL 引擎。
3. `OrderSignedStateFrameCodec` 回放 `STATE_BATCH_V1`，同时兼容旧 `STATE_UPSERT/STATE_REMOVE/STATE_ATOMIC_MATCH_V1`；Cold E2 与 Replica Delta 已共同调用该解码器。
4. 实际 `OrderFacade.commitPreparedRestingLimitQuote` 现走上述统一 batch 提交，而非特殊单状态提交。其他调用者逐步迁移，不做一次性危险热切。
5. `OrderCertifiedCrossPlan` 在**Maker 完全挂单且双方全额成交**时，接受 GTC/IOC/FOK 的限价 Taker，仍拒绝 FOK 部分成交、自成交、不同租户及无认证交易对。此处是纯业务计划的可行性，并不代表现网 IOC 成交链路已经启用。

### Trade
1. `TradeStateCoordinator.record`（旧先修改再记录）在 Common 模式下移除危险写入并拒绝，保留 `commitPreparedState` 这个唯一财务状态提交入口；未启用集群的旧模式保持无 WAL。
2. 新增 `TradePreparedExecutionHandler` 接口。五个已开发的 Trade 执行适配器实现 `supports/report` 和 `admit`；`Trade OrderFacade` 改成自动注入处理器列表，**不再写死 Newing/Cancel/Open/Close/Fill 逐条集群分支**。新增业务只需在 Trade 注册状态准备器，Common 和 Trade 公共分发不需添加业务类型。
3. 已实现适配器暂时保留原有 `@ConditionalOnProperty` 迁移开关，避免未通过真实物理 E2E 的资金行为被意外开放。这些是 Trade 功能灰度开关，不是 Common 的业务类型白名单。
4. 未找到处理器、多个处理器同时匹配或持久化失败都拒绝；任何情况不回退旧 `CheckManager` mutate-first 财务写入。

## 本地验收结果

- Order 全量 Java8 编译 **113** 主源码，通过；19/19 单元/回归，通过：IOC/FOK/GTC 状态机编码、共同 WAL 恢复、旧认证 Match Outbox、全额 IOC/FOK 撮合业务计划、Maker 网关防护。
- Trade 全量 Java8 编译 **164** 主源码，通过；32/32 回归，通过：任意 `sourceType` 的配置事务、多业务域嵌套身份校验、禁止旧 mutate-first 写入、通用业务处理器路由、开仓/双边成交/杠杆等。
- 不代表真实跨 JVM 物理签名证明或 SIGKILL HA 通过，也不代表 MySQL Projection 已提交。

## Demo 此刻的客观阻塞

- 运行中的镜像仍为 `local/otc-t225-ordersvr:certified-common-window` 与 `local/otc-t230-tradesvr:scoped-product-recheck`，均未切换。
- Order A/B、Trade A/B、Robot 运行，均 0 重启；查最近约 60s：Order A `ORDER_COMMON_MATCH_PLAN_NOT_YET_CERTIFIED` **38** 次，Order B **31** 次。
- `dc_orders_execorders.last_qty>0` MySQL 计数 **0**。Tape 持续送来真实 IOC，但旧部署还在拒绝。
- **NO-GO**：Order 通用批量状态写入和 IOC/FOK 计划已有；实际跨 Order/Trade 原子撮合 Outbox -> Trade 可信财务提交/确认 -> Projection 的可靠 Saga 仍未打通，且 Market/Partial/CLOSE 的完整状态准备还有业务工作。不能为了消除错误日志而关闭认证闸门、虚构 Filled 或部署新版无结算链路。

## 下一轮唯一优先线路

1. Trade 的双边 `TradeCertifiedPairFillAdmission` 接 Order 签名的 Match Outbox（不能信任任意未认证 RPC 财务请求），以可证明身份/来源的跨服务请求重试。
2. 从 Common Trade 签名 WAL/CommitIndex 提供可核验的结算状态回执；Order 只按可信回执记录结算确认，支持 A/B 重启后恢复 Pending。
3. Projection 从认证 WAL 投影出实际 Orders、Executions、Postings；真实 Robot 发送 IOC 到已持久化成交，并逐户检查资金持仓一致。
4. 最后再重新构建、在 Demo 替换镜像，跑 A/B 自动连续双向 SIGKILL、200 租户压力，不用 GitHub Actions。
