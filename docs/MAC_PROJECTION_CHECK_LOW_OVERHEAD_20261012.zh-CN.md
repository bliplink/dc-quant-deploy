# 2026-10-12 Mac Demo Projection 校验 OOM 复盘与低负担修正

## 已观察的真实故障

在 10 租户存续、Docker VM 8 CPU/约 16 GiB、MySQL 容器上限 1.5 GiB 的 Demo 上，运行旧版
`tests/check-projection-consistency-host.sh` 时，MySQL 在 Order Projection watermark 的全事件
`GROUP BY` 聚合 SQL 期间断开连接。Docker event 证实 `oom`、`die 137`、容器重启；
后续 Docker health 恢复 healthy。仅查看恢复后的 `State.OOMKilled=false` 会遗漏这次历史 OOM。

事故发生前后 Docker/Schema 只读盘点：`dc_order_projection_event` 约 116 万行，
`dc_trade_projection_event` 约 61 万行，`dc_trade_projection_mutation` 约 327 万行；
Order event 已有 `uk_dc_order_projection_partition_seq(partition_id,source_epoch,journal_seq)`
唯一索引；Trade event 的同顺序列是 PRIMARY KEY，Order/Trade watermark 各仅 10 行。

## 已修复并验证

- 不再把全部事件聚合/物化为临时表后计算末尾水位，改为对每条 watermark 的复合索引
  **反向顺序 LIMIT 1** 检索最大 epoch/seq，并确认该完整 tuple 确实存在。
  Order 显式要求复合唯一索引匹配；MySQL `EXPLAIN` 证实走 Backward index scan、
  不再出现 Using filesort。
- 真实 Demo Trade watermark mismatch=0，执行 **0.186 秒**；Order mismatch=0，执行
  **0.082 秒**；执行后 MySQL 为 healthy，重启计数仍为 1。
- 新增 `tests/test_projection_consistency_host_sql.py`，覆盖旧 epoch、落后 watermark、
  新 epoch、超前 watermark、缺失事件、多个分区场景。Bash 语法和 fixture 测试 PASS。
- 超大表的 `orphan_mutations`、`cross_partition_event_ids` 深度 SQL 加入
  MySQL `MAX_EXECUTION_TIME`，默认 15 秒，维护窗口可通过
  `PROJECTION_AUDIT_QUERY_MAX_MS` 调整（限 1,000–120,000 ms）。
  1,000ms 实际测试得到 MySQL ERROR 3024、脚本 **fail closed**，MySQL
  healthy、未再次重启；**超时绝不写成一致性 PASS**。
- 第一次修复后试跑完整校验发现约 327 万 mutation 的孤儿检查仍很慢：
  这次主动终止**仅属于验收的只读 SQL**，避免继续增加负担。随后加入上述超时保护。

## 验证范围限制与后续处理

**本轮通过的是 Order/Trade 两个 watermark 索引检查，不是完整 Projection
孤儿/跨分区审计 PASS。** 现有多百万行数据的全量 orphan 扫描应该放在独立只读库、
隔离维护窗口或改为分区/增量校验；在线 Demo 不反复跑无界扫描。

同期 Mac 真实检查：10/10 租户 Robot RUNNING、每租户 40 活动单、双边各 10 档盘口；
Order 256/256 分区 READY，256/256 Snapshot 集合一致，A/C 为 129/127 Primary。
MD 自动主切 preflight 仍 BLOCKED，MD-A/B Primary 未故障注入；Archive GC 未在活跃
Order/Trade 日志目录执行；Gateway 没有修改。测试脚本改动无需服务镜像重建，
亦未修改 MySQL 容器内存配置。
