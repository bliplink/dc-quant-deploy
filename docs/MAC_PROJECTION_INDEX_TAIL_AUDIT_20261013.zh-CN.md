# Mac Demo：Projection 索引尾部审计性能修复（2026-10-13）

## 实机发现与边界

在继续 Trade A/B 双向 HA 滚动上线门禁时，
`tests/projection_watermark_tail_gate.py` 的实时检查超时（65 秒）。
MySQL 的 `EXPLAIN` 显示两个相关子查询是 `DEPENDENT SUBQUERY`，
使用 `Using filesort`；这不适合作为百万级事件表的日常低开销验证。
一次超时期间查询还曾短暂留在数据库进程列表；
仅凭此故障**不能**判定 Projection 数据落后。

已调整成：先读取最多 256 条 watermark，再在同一 MySQL
客户端中按**严格校验过的分区常量**执行 B-tree 逆序 TOP 1
索引探针。Order 强制
`uk_dc_order_projection_partition_seq(partition_id,source_epoch,journal_seq)`，
Trade 强制
`PRIMARY(partition_id,source_epoch,journal_seq)`。
每条 SELECT 设置 MySQL `MAX_EXECUTION_TIME=1500`，
进程调用另有 30 秒上限。缺少事件、非法分区、重复
尾部、超出容量等全部 Fail Closed；没有扫描全部事件、
没有写数据库、没有更改交易热路径或 Gateway。

注意：各分区探针不是一条事务一致性快照；写入并发时
可能保守误报 BLOCK，因此结果仅是**Projection 数据库内部**
水位/事件尾部的必要条件，不授权 HA 主切或归档 GC，
也不代替权威 Order/Trade WAL committed HEAD、水位、
Replica、持仓、资金、订单及执行流水对账。

## 执行结果

- 原版在线查询：65 秒超时，MySQL 计划包含
  `DEPENDENT SUBQUERY ... Using filesort`。
- 新版在线查询：约 **0.76 秒**返回，
  `order_rows=10 trade_rows=10`，
  `PROJECTION_DB_TAIL_MATCH`。
- `python3 -m unittest discover -s tests -p 'test_projection_watermark_tail_gate.py' -v`：
  **9/9 PASS**，新增常量索引探针、非法分区、缺失尾部、
  重复尾部拒绝用例。
- 只读十租户验收：
  `PASS_10_TENANT_SNAPSHOT`；10/10 RUNNING，
  每户 40 活动委托，盘口双边各 10 档。
  私有证据：`~/.opentradingcore/trade-ha-progress-20261013-tenants.json`。
- Trade 256/256 ZK 分区目录读取成功，但 TradeSvrA 和
  TradeSvrB 的滚动重启门禁仍为 `BLOCK`。
  Snapshot A→B 有 4 个异常，B→A 有 7 个异常。
- WAL 只读审计：活跃文件实际分配
  `13847199744` 字节、归档 `67108864` 字节、
  512 个归档目录、48 小时到期候选 0、
  安全删除授权 0。证据：
  `~/.opentradingcore/trade-ha-progress-20261013-wal.json`。

## 后续必须通过的阻塞门禁

1. 将新 Trade 有签名温缓存/恢复机制在隔离测试中验证；
   现有在线 A/B 的恢复 source 与自动缓存开关未开启，
   **不得盲目重启当前唯一有效分区主副本**。
2. 在受控数据重建或独立副本演练环境让全量 Snapshot +
   WAL 完整 suffix、ZK epoch、持久 seal、Replica ACK
   形成同一权威水位证明。
3. Projection 数据库内部 MATCH **不等于**其追上权威
   Trade WAL；必须继续对账 committed HEAD 并验证归档 GAP。
4. 再做带真实持仓的主切、恢复、反向主切及资金/持仓对账。
   自动 GC 必须等待 48 小时与完整水位和 reader fence；
   TLS 不启用、Gateway 保持透传。

本次**没有**修改集群业务配置、切镜像、重启容器、
删除 WAL 或清理租户。
