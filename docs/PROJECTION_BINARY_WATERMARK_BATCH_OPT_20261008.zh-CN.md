# Projection Binary 批内水位 SQL 优化（2026-10-08）

**状态：源码、单测、GitHub Actions 完成；现网未部署，优化默认关闭。** 本方案不是修复 P054/P232 历史 GAP 的替代措施。

## 现网事实

- Mac mini 当前 ProjectionSvr 容器：`ghcr.io/bliplink/projectionsvr:sha-2d54c9d3234b948a8ed0a61e9b05c22b499d6f5a`。现网源码实际上来自独立仓库 `bliplink/com-app-dc-projectionsvr`，而非作为镜像发布入口的 `bliplink/com.app.dc.projectionsvr`。后者 CI 通过 `repository: bliplink/com-app-dc-projectionsvr, ref: saas-crypto` 拉取真正源码，再发布镜像。
- 运行配置 `projection.binary.enabled=true`、`projection.trade.binary.enabled=true`、`workerStripes=4`、`fetchMaxRecords=500`、`maxBufferedBatchesPerPartition=1024`。运行中的 class 证实为 `OrderProjectionBinaryConsumer` / `TradeProjectionBinaryConsumer`。
- 21:18 时 4min 的 Projection 日志有 **33 次** `Projection realtime buffer reset`；无 `REBASE_REQUIRED` 或 `PARTITION_BLOCKED`。实时缓冲区重置后依赖原始 committed journal 的 GAP fetch，不能将 buffer reset 当作数据丢失，也不能将它当作已经解决。需要进一步测每个分区的 committed high watermark / DB offset / GAP retry。
- 同时约 10s 的 **全局 MySQL** 状态变化：Com_insert=734、Com_update=454、Com_commit=229、Handler_write=2493。该指标是全库/所有服务的合计，**不能全部归因于 Projection**。
- Order A/B/C 仍运行旧镜像，ZooKeeper 6s session 仍出现过期，Docker VM CPU PSI some avg60≈77%，可用 RAM <1GiB；50/50 Robot 与 2000 活动报价仅表示这一时点报价状态，不等于 HA 稳定。

## 发现的实际 SQL 热点

`OrderProjectionService.applyWireBatch` 原先已把同一 partition 的最多500条事件放在同一个 MySQL 事务，但每条 `applyValues` 都执行：
1. `INSERT IGNORE dc_order_projection_watermark` 初始化行；
2. `SELECT ... FOR UPDATE` 锁定水位；
3. 严格检查前驱 `epoch/seq`；
4. `INSERT dc_order_projection_event` + 对非-demo 的 `dc_orders` / `dc_orders_execorders` 写入；
5. `UPDATE dc_order_projection_watermark`。

重复的 1、2、5 产生额外 SQL 往返和数据库行操作，即使整个批次只有一个数据库 COMMIT。

## 已提交的优化（显式 Opt-in）

真正源码仓库 `bliplink/com-app-dc-projectionsvr` `saas-crypto`：
- `OrderProjectionService` 增加 `projection.order.binary.watermarkBatchOptimized`（默认 `false`）。关闭时继续执行原有的逐条水位路径，保持兼容；
- 显式开启后，同一 partition 批次在一个事务中只执行一次 watermark 初始化和 `FOR UPDATE`，对每条事件在内存中按顺序验证前驱，业务事件及非 Demo 订单/成交仍逐条写入同一个事务，最后才更新一次 watermark 并 `commit`。发生错误回滚全部事件、订单及水位，旧 epoch 和重复事件仍不得推进水位；未更改 Journal、HA ACK/epoch/fencing 或 Trade 链路；
- `OrderProjectionBatchWatermarkTest` 包含连续事件、重放去重、缺口拒绝、跨 epoch 匹配和乱序拒绝等 5 项边界测试；完整 JDK8 Maven CI 与多架构 GHCR CI 通过（参见相关 Actions）；
- 生成脚本 `generate-saas-configs.sh` 明确设置 `projection.order.binary.watermarkBatchOptimized=${PROJECTION_ORDER_WATERMARK_BATCH_OPTIMIZED:-false}`，另有 `tests/test_projection_watermark_opt_in.py` 和集群配置 CI；**不在现网私有 env 打开该变量**。
- 原逻辑每 N 条事件有约 3N 次 watermark 专用 SQL；优化后约3次（只在水位真的推进时更新）。这只是语句数量模型，**不是实测订单 TPS 提升**。原本必须写入的事件、订单/成交 SQL 完全不省略。

## 上线门禁、验证与回滚

1. 先核实最新 canonical ProjectionSvr GHCR tag/digest、amd64/arm64 构建和回归测试通过。不得依赖本地临时镜像。
2. 隔离 MySQL / Projection 环境分别以开关 false/true 执行相同的 1/10/100/500 事件批次，比较事务提交后的 `dc_order_projection_event` 行、`dc_orders`、`dc_orders_execorders` 及 partition watermark 的一致性；对 demo=1 和 demo=0 分开覆盖。
3. 测试 duplicate replay、间隔丢一条、乱序、epoch 正确切换、旧 epoch、两个 worker 并发同一 partition、插入或提交前数据库连接断开，必须做到 fail-closed、无无水位提交、完整 rollback 后继续 GAP catchup。
4. 再核对 P054 Order 和 P232 Trade 历史水位，以及全部仍有 GAP 的 partition，不得“强行推进” offset 或删除 committed journal 绕过缺口。
5. 只有全部门禁通过并具备备份/回退、低负载滚动窗口，才用 **单独** ProjectionSvr 受控发布验证。上线初期保持 flag=false 做基线，之后在独立审批下启用 true 并统计 MySQL lock time、SQL statements/s、Projection lag、buffer reset、Robot active quotes、订单历史和持仓余额正确性；回退可先关闭 flag 并重启指定服务（需维护窗口），保留已提交数据。
6. TradeProjectionService 每事件仍单独执行 watermark 初始化/锁定/更新；为降低故障面，本轮仅优化 Order 流，不一起改 Trade 的水位语义，待 Order 端隔离验收后独立推进。
