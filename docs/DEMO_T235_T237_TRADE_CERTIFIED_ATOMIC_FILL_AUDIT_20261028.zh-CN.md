# T235–T237｜Trade 认证成交财务 AFTER-state 与双边提交（源码回归）

日期：2026-10-28，Demo 环境 `saas-crypto`，Mac 本地编译；**真实成交/跨服务 HA 仍 NO-GO**。

## 已完成源码

1. `TradeCertifiedOpenFillPlan`：完全基于不可变输入准备单笔全额 OPEN Limit GTC（两向持仓）成交的余额、冻结释放、仓位、占用保证金、手续费、持仓计算和财务回执。不调用旧 `ProcessOrder` 的 mutate-first 路径。拒绝跨租户、错订单身份、部分成交、冻结不足、负可用余额、非双向持仓。
2. `TradeCertifiedOpenFillAdmission`：复用 `TradeStateCoordinator.withCertifiedPartitionLock` 和 `commitPreparedState`，签名 WAL 返回后才从完全验证的业务帧应用余额、仓位、持仓订单删除、成交幂等回执。通过 `trade.common.certifiedOpenFill.enabled=true` 显式开启，默认不加载；目前尚未在 Demo 开启。
3. `TradeCertifiedPairFillPlan`：来自同一笔 Order 认证原子撮合的 Maker 和 Taker，合成一个租户 Trade 分区中单条 `TRADE_ATOMIC_MATCH_PAIR_PREPARED` 财务 batch；10 项变更包含双方的 ACCOUNT_BALANCE、POSITION、OPEN_ORDER REMOVE、手续费 POSTING、DEDUPE_RESULT。两个 ExecID 必须不同，价格/数量/交易对/租户一致、方向相反且非同用户。
4. `TradeCertifiedPairFillAdmission`：一条 Common 认证记录提交并应用双方财务状态，且先验证整帧再改变任何业务内存；两个 dedupe 生命周期锁稳定排序，重复结算必须全双边一致，半边旧成交必须 fail-closed。通过 `trade.common.certifiedPairFill.enabled=true` 显式加载，默认关闭。
5. `TradeCertifiedExecutionPostingProof`：手续费流水使用 `E2TRADE-<sha256(tenant,user,execId)>` 不变 ID；在应用/冷启动/副本恢复时绑定 5 项单边或 10 项双边 AFTER-state、报告 ExecID、订单、价格、数量、手续费回执。对原 `E2CASH-...` DB 现金入金证明路径保持原校验。
6. `ExecutionDeduplicator`：扩展 Trade 业务回执经济字段 SHA256 指纹，拒绝同租户相同 ExecID 对应不同订单或金额，保留既有快照/恢复容器。旧 Newing 字段指纹兼容；未直接修改现有 Demo 数据。
7. `OrderFacade` 在 Common 模式有独立条件式 OPEN Fill 入口；禁用时仍执行 `TRADE_COMMON_UNCERTIFIED_BUSINESS_PATH_DENIED` 保护。没有恢复旧的 mutate-first 路径。

## 实际回归

- Java 8 下 **163 个 Trade 主源码文件全量编译通过**。
- 10 个目标 JUnit suite 共 **41/41 PASS**：新 OPEN Fill 财务、Maker/Taker 双边账本、Common 签名回调、无 ACK 无变更、分区幂等、单用户收入、负向产品目录、原杠杆/取消/平仓委托路径及 PreparedState 校验。
- 测试中的 FakeCommon 只用于断言“签名回调之前绝不应用”和“单笔双边一次结算”，**不代表实际 RSA、双 Custody 或真实故障注入 PASS**。

## 运行范围与当前阻塞

- 运行中的 Order A/B 仍为 T225 镜像，Trade A/B 仍为 T230；MD A/B 的 Broker 价格开关已经开启且真实行情价格 `90001` 获验证，Robot 报价未停。
- 本次仅在开发源码中增加上述类与回归，没有开通新业务开关，没有将新的成交流程部署至运行镜像。
- **必须继续**：① Order 的 `STATE_ATOMIC_MATCH_V1` 持久化撮合事件与已认证/待结算 Outbox，② Order -> Trade 双边 matchKey 认证投递及重试，③ Trade 成交投影 `dc_orders`/`dc_orders_execorders` 和手续费流水的确定性消费与重建，④ 真实新租户 Gateway OPEN/CLOSE/成交/资金一致性 E2E，⑤ Order/Trade A/B 双向自动主切、WAL 丢尾自动认证恢复和性能。
- 不允许绕过 Common、打开旧撮合或将 41 项单测误宣称成真实成交。
## T238｜Order 已认证成交转换为确定性 Trade 双边结算事件

- Order 仓库 `saas-crypto` 本地 commit `8e5fc26`：新增 `OrderCertifiedMatchSettlementEnvelope`，直接从 `STATE_ATOMIC_MATCH_V1` 的双方 `Filled` 完整后状态生成 Maker、Taker 两份 `ExecutionReport`。包含 `ExecType=Trade`、`OrdStatus=Filled`、`OrderQty`、`LastQty`、`LastPx`、`OrigOrdPrice`、`LeavesQty=0`、Maker 标记、租户和用户身份；两个 ExecID 从签名 matchKey + 角色作 SHA256 派生，长度 31、跨重启保持不变。
- 避免旧 `splitOrderToExecOrder` 路径每次重试随机生成 ExecID，及旧 `ExecOrder` 转换缺少完整 Filled 状态/原委托数量而无法通过 Trade 的财务认证入站校验。
- Order Java8 全量 111 个源码文件编译 PASS；原子匹配、旧 Maker 门禁、原子 WAL 帧恢复和事件转换 11/11 JUnit PASS。
- **T238 仍未交付线上**：必须由 Order 的 Common 持久化 Outbox 实际持有并恢复待结算事件，经认证 RPC 把两个完整报告送入 Trade `certifiedPairFill`，在 Trade 物理回执确认后再签名落盘 Order 的结算确认水位；随后 Projection 消费。新代码尚未触发真实 Filled，Demo 保持 T225/T230 和 fail-closed。
