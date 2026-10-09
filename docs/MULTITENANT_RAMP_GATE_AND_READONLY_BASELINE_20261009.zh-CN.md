# 2026-10-09 SaaS 多租户只读基线与分批压测门禁

## 结论（夜间观测窗口）

**当前不能将 Mac mini Demo 直接推进到新增 50 或 200 租户。** 这是只读实时抽样而非 200 租户容量证明；尚未触发任何新租户注册、真实订单、资金动作或故障注入。

- `dc-saas-trade-web` 已运行 `eebbaa5`；MDSvr/Order/Trade/Robot、MySQL、Projection 均运行，原巡检时关键容器无 OOM/重启。
- 严格 12 租户 Chromium 检查 `10 PASS / 2 WARN / 0 FAIL`。12/12 都有 10 买档、10 卖档、200 条最近成交。`DPGR6B` 和 `UJ2WZD` 出现 `LAST_PRICE_RECOVERED_AFTER_GRACE`，不是完全通过。结果位于 E2E 容器 `/artifacts/market-readonly-20261009-night/survey-report.json`。
- ClickHouse `dc.market_trade` 抽样：总行数 `22117`，覆盖 `13` 个 location，最新落库距采样 `11s`，MDSvr 最近 `90s` 批量写入错误 `0`。**不能将行情存储行数或每秒入库数宣称为真实下单/撮合 TPS**。
- 最近 300s 按每户至少 2 条 `market_trade` 统计，有 `10/13` 个租户触发 WARN。最明显的 `ISMW9T`、`U6YQD4`、`VPDHPM`、`W8OSYE` 当时 300s 内 0 条。
- RobotSvr 最近 10min 日志经只读聚合，13 租户累计 `67` 次 `tape instruction`，`1` 次 `tape order skipped`。Tape 并非没有开启；`tape diagnostic` 上报的 `intervalAgeMs` 范围约 12–106 秒，明显高于代码默认 `tape_interval_ms=1000`（但实际在线数据库配置尚未核验，不能由此认定调度器失效）。`TradeReplayEngine` 有 5s/最多 100 个待处理周期的 backlog 上限，大量外部成交流量缩减不等于丢单。
- Docker 首次资源抽样：RobotSvr `76% CPU`，OrderSvr B `134% CPU / 2.51 GiB/3 GiB`，MySQL `1.28 GiB/1.5 GiB`；第二次 OrderSvr B `154% CPU / 2.477 GiB/3 GiB`。VM CPU PSI `some avg10=59.68%`，IO PSI `some avg10=0.15%`；更像 CPU/业务调用排队风险，**不能据此单独确认具体是 Java GC、线程池拥塞还是 OrderSvr 查询耗时**。磁盘约 92 GiB 可用。
- **新增只读准入脚本的第三次采样（UTC 15:47:37）：** `NOT_READY`，`4/13` 租户最近 5m 少于 2 条，CPU PSI `avg10=54.34%`，Order B 内存 `83.17%`，RobotSvr Docker CPU `76.25%`，5m ClickHouse 市场成交记录 `22` 条（均非真实订单 TPS）。该窗口的异常租户为 `BIHZYE`、`QVPT5V`、`U6YQD4`、`UJ2WZD`；与早先的 `10/13` 不同，说明活跃度随窗口波动，应连续观测，不能只凭一次采样作永久结论。


## 可重复使用的只读准入检查

```bash
python3 tests/check-tenant-ramp-readiness.py --output /tmp/otc-ramp-readiness.json
python3 -m unittest discover -s tests -p 'test_tenant_ramp_readiness.py' -v
```

脚本只使用 Docker `inspect/exec/stats`、`/proc/pressure/cpu`、ClickHouse `SELECT`。默认门槛：至少观察 10 租户、最近 5 分钟内 **至少 80%** 的租户有 >=2 行行情成交记录、CPU PSI `some avg10 <=25%`、Order B 内存使用率 `<=80%`、RobotSvr Docker CPU `<=85%`。任何遥测异常或缺失 **fail closed** 返回 `NOT_READY`。这些是谨慎的 Demo **初筛阈值**，不是经过压测推导出的容量 SLA。

即使全部达标，返回也只是 `BASELINE_READY_ONLY`、`nextRampAuthorized:false`；任何实际负载测试仍需独立的隔离租户、容量预算、压测脚本审批和回滚方案。不能把 `SELECT market_trade` 计数当作真正订单 TPS。

## 下一轮阻断项

1. **Tape 持续成交：** 采集 Robot Tape 调度队列等待、`openRobotOrders` 耗时、IOC 入队与最终执行 `ExecID`；查出为何每户 Tape 指令间隔数十秒，部分租户 300s 内无市场成交。注意不能把 Tape **指令**直接统计为实际**成交**。
2. **资源与高可用：** 观测 OrderSvr B CPU/heap/GC、MySQL 配置和 Docker VM 8 核 15 GiB 下 CPU PSI；无中断复测后再考虑调整 worker 并发数/IO。同一台 VM 的三副本不能作为跨物理主机 HA 证明。
3. **逐档压测：** 先确保全部现有租户持续报价/成交，再由 10 → 20 → 50 分批增加，每阶段记录 1m/5m TPS、P95/P99、订单/成交差异、CPU PSI、Memory/OOM、Projection watermark、ZK session、Robot active counts。有任一硬故障立即停止扩容。
4. **不要以此报告替代真实 Trader/Broker 签名交易、Order/Trade 故障注入或完整 Projection 一致性验收**；这些任务尚未通过。

本轮未修改当前服务参数、机器人设置或交易数据，未启动 200 租户压力测试。
