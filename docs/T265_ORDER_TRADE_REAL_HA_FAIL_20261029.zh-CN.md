# T265｜Order/Trade 真实 HA 故障注入与验收记录（2026-10-29）

## 结论：HA FAIL，不能宣布 READY

`saas-crypto` / Mac Demo，使用真实 Order A/B、Trade A/B、Common 物理 WAL 与 ZooKeeper；没有使用隔离单元测试冒充验收。本文件仅记录已观察证据，不是新的集群协议或恢复机制。

## 已通过的业务证据

- 全新租户 `ON8YOM`：自动审批、Maker/Tape 入金、Robot RUNNING、约 40 笔双边挂单、Tape IOC 指令均已在真实 Demo 验证；Bootstrap `COMPLETE/DONE`。
- Trade A 的 `P164` Epoch 2 认证 WAL 含双边 `TRADE_ATOMIC_MATCH_PAIR_PREPARED`。08:19 读取时，Order `P110` 的 `STATE_MATCH_SETTLED_V1` 与 Trade `P164` 以去掉 `PAIR:` 前缀后的 MatchKey **792/792 完全匹配**（0 缺失）。随后数量增长，故具体水位须随每次审计记录。
- 对最新认证水位的 Trade WAL 验算：08:xx 读取 `ON8YOM` 828 批双边成交、1656 条 POSTING；两个用户满足 `初始入金 + 累计手续费流水 = 当前余额`、`余额 - 已用保证金 - 冻结保证金 - 冻结手续费 = 可用余额`，均非负；使用 JSON Decimal 保持金额精度。此结果证明 Common-WAL 内已有真正的成交资金状态，并非公开 MD 最近成交已成功。
- AdminSvr `querySymbol` 全量缓存修复已提交 `ae3a156`、自动 `VERIFY` 幂等恢复已提交 `0d35da4`。Trade 新开户 HEDGE 配置按需读取并缓存已提交 `dd362da`，新 JUnit 2 项通过。当前 Demo Admin/Trade 使用相应本地镜像。

## 失败 1：真实 SIGKILL 没有自动主切

- **08:25:17**：真实执行 `docker kill -s KILL dc-saas-ordersvr-b`，退出 137，未自动重启。故障前 `P045` 的主节点为 `OrderSvrB/Epoch2/READY`，两端原始认证 WAL/HEAD/Receipt 均为 seq 37096。
- **08:25:44（故障约 27 秒后）和 08:26:24（故障约 67 秒后）**：ZooKeeper `P045` 仍报 `OrderSvrB/Epoch2/READY`，没有由 A 自动接管；实际 EPHEMERAL leases 列表仅剩 `[OrderSvrA]`。`P110`、`P180` 虽由 A 担任 Primary，但日志持续报 `Common physically certified partition writer unavailable`，Robot 下单中断。
- Common 源码虽有 `CommonCertifiedFailoverWatch` 和 `CommonCertifiedFailoverCoordinator`，查遍 Common/Order/Trade 的主源码没有发现 Watch 被常驻服务实例化启动。配置中旧 `order.cluster.failover.enabled=false`、`trade.cluster.failover.enabled=false`、服务私有 replication 均关闭；**不可用重新打开旧服务集群机制来解决**，应在通用 Common runtime 闭环接线和验收。

## 失败 2：旧 Epoch 写入中断后重新加入失败

- **08:26:41**：重新启动 B；**08:28:38**：Order B 退出码 1。完整异常链根因 `java.io.IOException: Common physically fsynced WAL head mismatch`，不是 MySQL、Gateway 或 Java 类不存在。
- **08:30:32**：停止 Robot 以保存证据，`tests/t248_audit_common_physical_certified_integrity.py` 只读检查 512 分区，`errorCount=4`：
  - `Order P110`：A signed HEAD `(E2,6935)`、Receipt `(E2,6934)`；B WAL seq 6935、signed HEAD `(E2,6934)`。
  - `Order P180`：A WAL seq 49831、HEAD/Receipt 49830；B WAL seq 49830；A/B WAL 不同。
- **不可**反复裁剪 WAL 或手改 HEAD 来宣告 HA 通过。必须将未认证尾部完整保留证据，验证双方最后共同认证的前缀后由 Common 统一进行安全重建、续传和重启恢复；能否本地 ACK 后继续写入需在明确保障单主的授予协议中验证。单节点存活期间业务不应受已死副本阻断。

## 失败 3：已认证成交未到下游

- MD `queryPublicMarket` 可返回 20 档盘口，但 `recentTrades=0`；现有 MD 订阅 `dc.order.trade.<symbol>.1.**`，而签名 settlement 代码已写 Trade WAL 和 Order ACK，却未执行原有 `PublishOrder.OnTrade` 成交发布路径。只能在**认证 Trade 结算回执 + Order ACK 物理持久化后**发布真实成交；重复/恢复后须有按 MatchKey 去重，不能假造成交。该源码修改曾被执行环境的安全检查拦截，未生效。
- MySQL `dc_trade_projection_event` 仍为空，`dc_users_balance` 仍是新租户初始 10000，和 WAL 内的真实手续费/持仓状态不同步。ProjectionSvr 目前持续 `ORDER_COMMON_PROJECTION_COMMIT_INDEX_NOT_CONNECTED` 与 `TRADE_COMMON_PROJECTION_COMMIT_INDEX_NOT_CONNECTED`。直接检查 `FetchCommittedOrderProjectionEventsHandler.fetch` 和 Trade 同名处理器，均是返回该错误的未接线占位实现；不能把 ProjectionSvr 容器 Up 当成投影有效。应从 **Common 已认证 WAL** 提供通用 committed-window 读取，业务服务只把已有消息转换为投影事件，不另建复制日志。

## Demo 当前状态（08:30 之后）

- Order A 运行但部分分区写入不可用；Order B **Exited(1)**，未经人工改写证据不会正常重启；Trade A/B 运行；Robot **主动停止**以避免制造不确定的新 WAL 尾部；ZooKeeper 运行。不要声称 Demo 完整健康。
- 原始证据保留在原 Demo 数据目录；勿在核对前覆盖。此处未执行 Trade 故障注入，也未完成 A→B→A 自动互切、资金/持仓 SQL 投影核验或 10/50/200 租户压力验收。

## 下一步一次性验收门禁

1. 保持 Common 与业务解耦：Common 只管 byte[] 状态机、认证 WAL/复制、快照/归档、可恢复提交边界和失效主节点自动撤权；不识别 GTC/PO/IOC/FOK、余额或业务类型。
2. 将现有 Common 节点级 watcher/恢复/存活单主写入接成真正**自主、可重启、可续传**的 A/B 流程；在全量真实镜像部署验证，不再以隔离测试替代 Demo。
3. 先修复本次 P110/P180 的持久化分叉根因和安全恢复，确保 B 重启、A 继续正常写入；不要把手工 WAL 清理当 HA 自动通过。
4. 再补已认证成交的原有 MD 推送以及从 Common 认证窗口到 Projection 的业务投影；核对两个交易员的手续费、余额、持仓、成交、订单，确认 MD recentTrades > 0。
5. Robot 保持报价与真实成交，分别对 Order A/B、Trade A/B 做实际 SIGKILL → 自动接管 → 自动追平 → 反向 SIGKILL，要求无双主、无丢单、无重复成交，才可把验收从 FAIL 改为 PASS。
