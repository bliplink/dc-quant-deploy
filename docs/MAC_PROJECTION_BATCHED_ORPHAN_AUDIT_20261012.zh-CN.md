# 2026-10-12 Projection 百万级孤儿审计分批化及真实 Demo 小范围验证

## 目标与变更

前次 `tests/check-projection-consistency-host.sh` 的数百万行整表 join/聚合可能引起
MySQL 1.5-GiB 容器 OOM。仅增加 SQL `MAX_EXECUTION_TIME` 不足以抵御
**超时之前的峰值内存**。本次保持线上服务、数据、Gateway 不变，将 mutation orphan
检查改成 `scripts/check-projection-orphans-batched.py`：

- 首先按 `dc_trade_projection_mutation` 复合主键反向索引取本轮固定上界，
  每页最多默认 10,000 个 mutation，按主键升序以 keyset 读取下一页。
- SQL 在含 `LIMIT` 的派生表中先物化**有界的主键页**，再利用
  `dc_trade_projection_event` 主键等值 join，不对整张 mutation 表执行
  大型临时关联。每批 `MAX_EXECUTION_TIME` 默认 10 秒；Docker MySQL
  调用也设置硬超时。
- 任一 orphan、主键游标倒退、上界记录在扫描中消失、单条 SQL 失败、最多页数/
  总运行期限耗尽均 **fail closed**，不再声称全量一致。独立输出 JSON 证据，
  不覆盖已有报告；不操作任何业务数据、归档和服务进程。
- 本算法遍历的是**活跃写入数据库的一段固定键范围**，不是一个跨页
  MVCC 一致性快照：历史区间在扫描过程中被异步补写仍可能漏检。
  因此即使完成本轮扫描，也只会给出
  `PASS_LIVE_RANGE_OBSERVATION_ONLY`，始终
  `authoritativeAttestation=false`；正式 durable attestation 仍需要在受控
  Snapshot/CDC watermark 下验证。
- Trade `event_id` 跨分区冲突由全量 `GROUP BY` 临时表改为带
  `idx_trade_projection_event_id` 的 EXISTS + LIMIT 1 存在性检查。
  发现任意跨分区重复时脚本现在直接失败，不再只打印 INFO。

## 实际 Mac 只读验证

1. 当前 MySQL Docker health=healthy，OOM 后 restartCount=1 未新增；
   Order/MD/Gateway 未在本轮重启。
2. 实际读取 6,000 个 mutation（分 3 批、每批 2,000），耗时
   **0.964 秒**，`orphanMutations=0`，固定上界
   `[P246,2,178503,3]`。因为用户指定只扫 3 页，
   正确输出 `PARTIAL_NOT_ATTESTED`（exit 2），**没有误称全量通过**。
3. 经主验收脚本再次以 1 页 × 2,000 条运行，观察
   `PARTIAL_NOT_ATTESTED`，主脚本拒绝 PASS；MySQL 仍 healthy、
   restartCount=1。该批因持续交易有后续上界，测试记录时上界为
   `[P246,2,179131,3]`。
4. `python3 -m unittest -q tests.test_projection_orphans_batched
   tests.test_projection_consistency_host_sql tests.test_md_failover_preflight
   tests.test_md_recovery_shadow`：**29/29 PASS**。包括：一致多页扫描、
   缺失 event 即失败、页数封顶不误报、上界被并发删除时拒绝、
   不安全游标、跨分区同一 eventId 检测、历史 gap 允许已恢复等。

## 运行与边界

生产用单次完整审计可执行（现场配置来自私有环境文件，请勿提交）：

```bash
ENV_FILE="$HOME/.opentradingcore/local-ha-zkfix-20261011-v1/artifacts/local-ha-runtime.env" \
PROJECTION_ORPHAN_CHUNK_SIZE=10000 \
PROJECTION_ORPHAN_MAX_SECONDS=90 \
PROJECTION_ORPHAN_QUERY_TIMEOUT=10 \
bash tests/check-projection-consistency-host.sh
```

默认最多 1,000 页，每页 10,000 条，运行上限 90 秒。若超过任一上限，
整个脚本 **失败并保留检查报告**，而不是称业务一致。线上持续活跃写入时，不可把
`PASS_LIVE_RANGE_OBSERVATION_ONLY` 当成 Archive GC 或 MD 晋升许可证。

**本轮不宣称 327 万条 mutation 全量通过**：已完成隔离测试及实际 6,000 条观测。
MD-A/B 主节点故障注入、MD 自动主切和真实业务归档 GC 仍保留独立安全门禁；
所有此类开启操作均须有可靠的 Order 物理主备/持久水位、旧主 fencing、
完整 Image+Delta 以及 Archive Replica/Projection/Backup 证明。
