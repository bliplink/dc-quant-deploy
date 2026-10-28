# T241｜Order ↔ Trade 签名原子成交 Saga 源码接线验收（2026-10-28）

**结果：源码 / Java 8 测试通过；当前 Mac Demo 真实 Filled / 物理 HA / Projection 均未验收，NO-GO。** 研发分支全仓为 `saas-crypto`。本轮不改 Common 集群代码、不修改运行中的 Order/Trade Docker 镜像、不重置已有数据，不使用 GitHub Actions。

## 本轮源码变更与可复验提交

| 仓库 | 提交 | 业务边界 |
|---|---|---|
| `.work/com.app.dc` | `6461e9a` | 公共业务 RSA 消息 `OrderTradeSignedMatch`、`TradeOrderSignedReceipt`，不在 Common 添加任何类型/持仓/订单解析 |
| `.work/ordersvr` | `31fb9c8` | 真实 `CrossStrategy` 完整成交分支、Order Common 原子 Match WAL、可从认证 WAL 重建的 Outbox、RSA 节点签名、Gateway 异步重试、结算 ACK 再写一条 Order Common WAL |
| `.work/tradesvr` | `70d623c` | 验证预先固定的 RSA 公钥、Common Primary 校验、调用已有一次十项状态变更的双边结算、财务成功后签 RSA 回执；已有 MySQL `position_way_type=HEDGE` 在 Trade 加载层转换为 `0` |

### 完整成交业务事件链

1. Order 校验风险已批准的订单 + 当前同分区盘口；`CrossStrategy` 对**Maker/Taker 数量完全相等、全额成交的限价 GTC/IOC/FOK**纯业务准备双方 Filled 状态，不直接修改内存。原子 `STATE_ATOMIC_MATCH_V1` 是一条业务 WAL，Common 仅复制/持久化和物理认证。
2. Common physical ACK 之后，Order 应用双方书本状态，并把**同一已认证的原始 Order WAL 帧**投影到 Pending Outbox；冷恢复与线上 Replica Common 认证帧恢复同样重建 Outbox。
3. Order Primary 用已挂载的本节点 RSA 私钥签署原始帧标识 + Maker/Taker 完整经济事件，经 Gateway `settleSignedOrderMatch` 发给 Trade。重试使用原始 MatchKey 和确定性双方 ExecID。**不会把任何普通 RPC 请求或没有 Order Common 确认的匹配直接转财务。**
4. Trade 验证预设固定公钥、原始 Order 帧身份、Maker/Taker 租户与产品、当前 Common Primary，再在 Trade **自己的**一个 Common WAL 批次中提交十项资金/持仓/订单去冻结/手续费 Posting/去重状态。不会走旧先改内存后记账。
5. Trade 认证提交成功后按自己节点 RSA 签 `TradeOrderSignedReceipt` 回执，Order 验证且核对原 MatchKey/Order 分区/epoch/sequence/租户，写入**Order 自己的** `STATE_MATCH_SETTLED_V1` 通用 Common WAL。重启/新主恢复这条确认后，不再把已完成撮合当 Pending 重投递。未收到回执/回执签名错误/ACK WAL 未提交则保留 Pending、稍后按原 MatchKey 幂等重试。
6. 两个新服务间功能开关默认关闭，须在真实物理 JVM 与风控/Projection/恢复验收后启用：Order `order.trade.signedMatch.enabled=true` + `order.trade.signedMatch.delivery.enabled=true`；Trade `trade.orderMatch.signedRpc.enabled=true` + `trade.common.certifiedPairFill.enabled=true`。不能只打开其中一侧。

### 实际源码验证

- 两个共享 RSA 业务协议 + 篡改拒绝：**6/6 PASS**（共享业务源码 Java8 直接编译）。
- Order **117 个 Java8 主源码文件编译 PASS**；本轮相关八组回归 **25/25 PASS**：真实 `CrossStrategy` 全额 IOC/FOK/GTC 分发、Pending 签名、RPC 拒绝重试、Trade RSA 回执写入（测试中的虚拟 Common ACK）、认证 WAL Cold/Replica 恢复之后 `Pending=0`、兼容旧单订单和新批量帧。
- Trade **166 个 Java8 主源码文件编译 PASS**；相关六组回归 **19/19 PASS**：已签 RSA 双边结算请求、假 Common 原子 ACK / 拒绝、幂等不双扣、签回执、不同客户手续费、数据库 `HEDGE\u21920` 等。
- Mac 没有可调用的 `mvn`：尝试 `mvn -o -DskipTests package` 失败，命令不存在。使用已有本地构建依赖 `target/dependency/*.jar` + Java 8 `javac` 进行全量主源码编译，并从已有共享 jar 创建独立测试用 JAR：`.work/com.app.dc/target/t241-com.app.dc-0.0.4-SNAPSHOT.jar`，经 `jar tf` 验证 4 个新协议 class 均在包中。**不是正式的 Maven Release，也没有生成/部署 Docker 镜像。**
- 三仓本地 git 已提交，未声称已推送 GitHub，未运行 GitHub Actions。

### 仍不能对外宣布“Robot Tape 会持续成交”的原因

- 实际 Demo 旧镜像仍在 `CrossStrategy` 禁止完整 IOC 撮合；数据库真实 `dc_orders_execorders.last_qty>0` 尚为零（复查以最后一次工具结果为准）。
- 此次只处理单对 Maker/Taker **数量完全相等**的全额 `OPEN+Limit`；Tape 数量可能是 0.0002、0.0003，Maker 盘口对应剩余数量可能并不相等。真实应支持多个对手单、部分成交、剩余 IOC 取消、FOK 全成交判定、Market、Close 等；不可把这些交易类型全部通过一个人为门禁。
- **Trade 双边财务结算已有内存+FakeCommon 回归，尚未证明实际 ZooKeeper/独立物理签名/Netty A/B 2/2 WAL 和恢复一致性。** 服务端 RSA 来源鉴权基于 Demo 目前共用的已挂载 Common demo 密钥目录；这是节点业务签名，而不是一个独立可公开验证的跨服务 2/2 CommitIndex 证书。若生产服务需完全隔离，必须给 Order/Trade 分配独立身份和源证书验证。
- Projection 仍缺从 Common 认证 WAL -> MySQL 成交、资金 Posting、订单流水的消费和重放验证；当前已有 `FetchCommittedTradeProjectionEventsHandler` 显式错误 `TRADE_COMMON_PROJECTION_COMMIT_INDEX_NOT_CONNECTED`，不能凭成功内存账务让数据库展示 Filled。
- 后续对真实 Docker A/B 的连续自动双向切换、旧主隔离、重复/漏单/重复成交流水验证、10/50/200 租户、归档/快照仍未完成。

## 下一步按单一业务状态机推进

让同一 Order 撮合状态机产出**一条内含多腿部分成交、剩余挂单或取消的 after-state batch + 可靠结算业务事务**，Trade 对这些执行报告统一聚合到一次 Common 财务状态提交；补 Common 认证投影消费并部署全量新镜像做真实 Tape+资金与主备验收。不要再为 IOC/FOK/Market/资金分类新增 Common 适配器或旁路 WAL，也不要启用尚未通过真实验证的交易支路。
