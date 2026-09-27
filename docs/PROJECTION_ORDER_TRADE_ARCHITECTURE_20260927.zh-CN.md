# ProjectionSvr 订单与交易投影架构基线

## 1. 生产职责

ProjectionSvr 是交易核心的异步持久化/查询投影层，不参与 OrderSvr/TradeSvr 的同步业务决策。

- OrderSvr -> ProjectionSvr：订单及执行状态事件。ProjectionSvr 按分区、epoch、sequence 拉取并幂等应用，持久化订单查询模型（包括 `dc_orders`）。
- TradeSvr -> ProjectionSvr：资金、持仓、成交、funding 等交易域事件。ProjectionSvr 按 Trade 分区独立维护 watermark 并持久化交易查询模型。
- Order 与 Trade consumer 必须独立恢复；一条链的 GAP/历史坏事件不得被当成另一条链成功的证据。
- OrderSvr/TradeSvr 的本地 RocksDB/日志属于核心状态恢复机制；MySQL 投影不是同步交易链的前置依赖。

## 2. 集群路由

逻辑服务名与物理节点必须分离：

- `SERVER.OrderSvr` -> PartitionRouter -> `OrderSvrA` / `OrderSvrB`
- `SERVER.TradeSvr` -> PartitionRouter -> `TradeSvrA` / `TradeSvrB`

ProjectionSvr 配置使用逻辑 key：

- `projection.binary.orderServerKey=SERVER.OrderSvr`
- `projection.trade.binary.tradeServerKey=SERVER.TradeSvr`

但 ProjectionSvr/GW 必须预连接物理 A/B 节点，PartitionRouter 才能把分区 primary 映射到在线连接。A/B 的 `serverKey` 不能退化成共同的 `SERVER.OrderSvr` 或 `SERVER.TradeSvr`。

## 3. 恢复与验收不变量

1. OrderSvr/TradeSvr 分区达到 READY 后，ProjectionSvr 必须能重新建立 A/B 物理连接。
2. Order consumer 必须证明新订单从 OrderSvr journal 到 `dc_orders` 收敛。
3. Trade consumer 必须证明资金、持仓、成交/funding 从 TradeSvr journal 到查询库收敛。
4. Projection GAP retry、`event exists ahead of watermark`、长期 watermark 不推进均视为验收失败，不能只凭服务进程存活判 PASS。
5. Core 与 Robot 全链路验收串行执行，避免恢复/重启互相污染。

## 4. 当前已验证事实（2026-09-27）

- Order 分区恢复达到 256/256 READY 后，ProjectionSvr 重启可发现 OrderSvrA/B 与 TradeSvrA/B。
- Order binary consumer 已恢复，新 location `PROJ_115134` 的 maker 投影为 `New`，FOK taker 投影为 `Cancelled`。
- Trade binary consumer 的跨分区 funding `event_id` 冲突已定位并修复：durable identity 改为 `(partition_id, source_epoch, journal_seq)`；P064 watermark `3291 -> 3299`、P094 `1261 -> 1269`、P110 `21519 -> 24715`、P254 `331 -> 335`，同一 funding `event_id` 已验证可跨分区共存且不再触发 GAP retry。
- ProjectionSvr 修复已提交到正确生产仓库 `bliplink/com-app-dc-projectionsvr@84f9863`。

## 5. 源码与构建基线

- 当前生产 ProjectionSvr 源码仓库固定为 `bliplink/com-app-dc-projectionsvr`，分支 `saas-crypto`。
- 旧仓库 `bliplink/com.app.dc.projectionsvr` 不得用于 SaaS 生产镜像构建。
- Trade projection 的 durable identity 是 `(partition_id, source_epoch, journal_seq)`；`event_id` 仅作为业务关联标识，不能作为跨分区全局唯一键。
- funding 等业务事件在 partition reassignment 后允许相同 `event_id` 出现在不同 partition；验收必须覆盖该场景并验证 watermark 可继续推进。

## 6. 运维约束

- 单服务维护或验收启动必须避免隐式重建依赖；使用 Docker Compose 时优先 `up -d --no-deps <service>` 或等价的单容器操作。
- Projection 验收禁止通过重启 OrderSvr/TradeSvr 来“制造通过”；先用只读一致性检查确认 event / mutation / watermark，再单独判断上游连接状态。
- 当前只读一致性 gate：Trade event 主键为 `(partition_id,source_epoch,journal_seq)`，mutation 主键为 `(partition_id,source_epoch,journal_seq,mutation_index)`；Order/Trade 现有 18 个 watermark 均与 durable tail 一致，orphan mutation 为 0。
