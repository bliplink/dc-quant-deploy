# TradeSvr 集群实现与验收边界

## 当前状态

TradeSvr 的集群底座已经从“冷备骨架”进入可部署验收阶段。

当前 `saas-crypto` 已具备：

- 按 `location` 路由到稳定逻辑分区 `P000~P255`。
- TradeSvrA / TradeSvrB 使用相同不可变镜像，独立 `serverKey`、Gateway 端口、replication 端口、journal、snapshot 和日志目录。
- Partition Primary / Replica、epoch fence 与 readiness gate。
- authoritative post-state `STATE_BATCH` journal。
- durable `STATE_COMMIT` watermark。
- A/B 同步复制和 replica ACK。
- snapshot + committed delta recovery。
- recovery 完成后才允许 partition promotion / READY。
- CashIn / CashOut、Funding、账户配置、杠杆、持仓模式、BanAccount、Bankruptcy、Position ADL、普通 ExecutionReport 和 legacy liquidation ADL 候选账户等 authoritative mutation 已接入状态 journal。
- ProjectionSvr 可独立消费 TradeSvr committed binary stream，并维护独立 Trade watermark / GAP recovery。
- Trade recovery replay、recovery-gated promotion、Projection committed reader 和各业务 STATE_BATCH recorder 已加入自动化测试。

## 部署模型

启用：

```text
TRADE_CLUSTER_ENABLED=true
```

后生成：

```text
TradeSvrA
  Gateway port: TRADESVR_GW_PORT
  Replication: TRADESVR_A_REPLICATION_PORT
  journal: ../../data/TradeSvrA/journal
  snapshot: ../../data/TradeSvrA/snapshot

TradeSvrB
  Gateway port: TRADESVR_B_GW_PORT
  Replication: TRADESVR_B_REPLICATION_PORT
  journal: ../../data/TradeSvrB/journal
  snapshot: ../../data/TradeSvrB/snapshot
```

A/B 都启动完整业务 runtime：

```properties
trade.node.businessEnabled=true
```

是否允许业务写入不再通过静态 A/B 身份决定，而由：

```text
partition assignment
+ Primary ownership
+ epoch fence
+ recovery lifecycle
+ READY gate
```

共同决定。

因此 Replica 可以保持热状态，但在未成为当前 READY Primary 前不能承载 authoritative mutation。

## HA 配置

Trade 集群模式生成的关键配置包括：

```properties
trade.cluster.journal.enabled=true
trade.cluster.state.commit.enabled=true
trade.cluster.state.required=true

trade.cluster.snapshot.enabled=true

trade.cluster.lifecycle.enabled=true
trade.cluster.recovery.authoritative=true

trade.cluster.replication.enabled=true
trade.cluster.replication.peers=TradeSvrA=127.0.0.1:<A_PORT>,TradeSvrB=127.0.0.1:<B_PORT>

trade.projection.binary.enabled=true
```

ProjectionSvr 同时启用：

```properties
projection.trade.binary.enabled=true
projection.trade.binary.tradeServerKey=SERVER.TradeSvr
```

当 Order 集群同时启用时，ProjectionSvr 还启用独立的 Order binary consumer；Order 和 Trade 使用各自独立 watermark，不共享恢复进度。

## 已完成的代码/CI验收

TradeSvr 当前代码验证已经覆盖：

- authoritative mutation journal
- committed state replay
- recovery planner / applier
- recovery-gated promotion
- replication transport
- Projection committed reader
- Trade binary consumer 状态机
- 服务编译
- Docker 镜像构建与 GHCR push

这些验证说明代码和镜像具备进入真实多节点部署验收的条件。

## 2026-09-19 验收状态与剩余宿主机门禁

当前代码/CI 已继续补齐：

- ProjectionSvr Trade binary consumer 的 GAP catch-up、buffer drain、BASELINE_MOVED/rebase 测试；
- Order/Trade Projection durable watermark 的重启连续性与不回退检查；
- 核心真实交易后 Order/Trade watermark 必须实际推进；
- `run-trade-cluster-role-reversal-host.sh`：A→B→A role reversal、READY、epoch/version 和 Projection 连续性；
- `acceptance-saas.sh`：把真实交易、强制压力、Robot、role reversal 和最终 health validation 串成统一门禁。

因此“缺少 failover/role reversal/Projection GAP 自动化”这一旧缺口已经关闭。仍不能仅凭 CI 把某台部署主机定义为“生产 HA 已验收”：目标 Linux/Docker 宿主机必须真正执行 `install-saas.sh --full-cluster -> acceptance-saas.sh` 并得到最终 PASS。

统一宿主机验收会覆盖/验证以下目标：

1. 使用固定不可变 TradeSvr 镜像启动 A/B。
2. bootstrap 256 个 partition assignments。
3. 验证每个 partition 只有一个 READY Primary。
4. 产生真实业务 mutation：
   - 普通成交
   - CashIn / CashOut
   - Funding
   - Leverage / PositionType / AccountConfig
   - BanAccount
   - Bankruptcy
   - ADL
5. 校验 Replica journal / commit watermark 持续追平 Primary。
6. kill 当前 Primary。
7. 验证 Replica 通过 snapshot + committed delta recovery 后 promotion。
8. 验证旧 Primary 不可继续写，防止双主。
9. 验证角色反转后继续产生业务 mutation。
10. 对比 failover 前后：
    - AccountBalance
    - Position
    - AccountConfig
    - SymbolPara
    - OpenOrder
    - execution dedupe
    - committed watermark
11. 验证 ProjectionSvr Trade watermark 连续推进，并能从 GAP / 重启恢复。
12. 再执行反向 role reversal，确认 A/B 均可承担 Primary。

只有目标宿主机上的统一验收全部通过，才把该部署实例的 TradeSvr A/B 标记为通过 HA 验收；仓库级 CI 只证明代码与验收入口具备执行条件。

## 与 MDSvr / OrderSvr 的关系

MDSvr A/B/C 已有真实生产滚动迁移和 READY 门禁验收，不在本轮 Trade 改造范围内。

OrderSvr 已具备 journal、state、commit、snapshot、replication、recovery lifecycle 和 Projection binary 路径。

最终交易核心部署目标为：

```text
MDSvr A/B/C
      │
      ├── market data
      │
OrderSvr A/B ── committed binary ──┐
      │                            │
      └── executions               ├── ProjectionSvr
                                   │
TradeSvr A/B ── committed binary ──┘
```

四块统一依赖 partition assignment、epoch fencing 和 READY gate，避免以“容器存活”代替“节点可写”。

## 启用原则

- 默认仍保持 `TRADE_CLUSTER_ENABLED=false`，不影响当前单节点部署。
- 先在隔离/验收环境启用 A/B。
- 必须使用同一版本不可变镜像和同一套公共依赖。
- 未在目标宿主机完成 `acceptance-saas.sh`（含 role reversal、Projection 连续性和压力门禁）前，不把该实例标记为生产 HA 验收通过。
- 任一 partition recovery、replication 或 READY 校验失败时，应保持该 partition fenced，而不是绕过门禁继续写。
