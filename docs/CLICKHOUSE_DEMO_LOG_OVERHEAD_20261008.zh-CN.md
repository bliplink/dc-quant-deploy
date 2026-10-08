# ClickHouse Demo 内部日志 CPU/磁盘开销与安全部署

状态：**仅代码与 CI 完成；现网尚未应用。** 2026-10-08 实测；本方案不直接解决 OrderSvr 复制与 ZK 心跳问题。

## 现场基线

- Colima/Docker VM：8 vCPU、约 16 GiB；CPU pressure some avg60 高于 60%，MemAvailable 低于 1 GiB。
- `dc-saas-clickhouse` 一次 CPU 采样约 76%，容器 RSS 约 1.2GiB/2GiB。
- `system.parts WHERE active` 观察到 `system.trace_log` 约 1.76 GB / 1.13 亿行，`system.text_log` 约 564 MB，`system.metric_log` 约 85 MB，实际 `dc.kline` 约 147 KB。
- ClickHouse 重度日志扫描会因 server memory limit 被终止；不要在高压现网反复执行 `SELECT count() FROM system.trace_log` 等全表聚合。

## 已提交的低开销日志设置（未部署）

`clickhouse/config.d/90-saas-demo-quiet.xml` 禁止新产生五种内部诊断/统计日志：`trace_log`、`text_log`、`metric_log`、`asynchronous_metric_log`、`processors_profile_log`。

它**不会修改或删除已存在的 system 表与历史数据**，保留 `system.query_log`、`system.error_log`、`system.part_log`、`system.crash_log` 和常规 ClickHouse 文件日志，适用于不需要持续 stack profiler 的单机 Demo。运维调试如需内部 trace，应暂时回退该设置后重建 ClickHouse。参见 ClickHouse 官方配置实现和文档（remove 属性）；任何生产多节点集群须另行评估。

`compose.yaml` 已添加单文件只读挂载：`./clickhouse/config.d/90-saas-demo-quiet.xml:/etc/clickhouse-server/config.d/90-saas-demo-quiet.xml:ro`。

测试 `tests/test_clickhouse_demo_log_config.py` 验证合法 XML、只禁用指定五种内部日志、保留业务存储卷和重要错误/查询日志；CI 已通过。**仅改 repo 文件不会自动替换已经运行的 Docker mount 或启用配置**。

## 受控上线门禁（均需满足）

1. 保存现网 ClickHouse Compose 有效配置与 `docker inspect` 镜像、挂载和环境、采样 CPU/内存；确认使用**正确的部署 worktree**及 `saas-crypto`，确保变更范围只包含 ClickHouse，不修改其它服务或镜像。
2. 检查 ClickHouse 数据卷 `/var/lib/clickhouse` 和配置持久化仍绑定原路径；验证 XML 合法和版本兼容。**严禁 `DROP/TRUNCATE` system 或 `dc` 表、清理 journal/快照或删除 volume。**
3. 审核与 Order/Gateway/APSSvr 的依赖关系、确认短时间 ClickHouse 不可用不会造成订单丢失或同步复制阻塞；在业务低峰、CPU/内存压力可接受时才允许受控 ClickHouse-only 重建。当前高 CPU pressure 和 Swap 近乎耗尽，**NO-GO**。
4. 只重建 ClickHouse 服务（切勿 `docker compose up` 整套），完成健康检查和 `SELECT 1`、`dc.kline` 读写链路的只读验收；前后观察 5–10 分钟 CPU pressure、ClickHouse CPU、`system.parts` 的日志活动部件增长、业务盘口与 50/50 Robot、Order ZK Expired、Projection 状态。
5. 如果业务接口报错、ClickHouse 重启或 kline 读取异常，则用备份 Compose/配置**只回滚 ClickHouse 挂载**，保留数据卷，复核容器健康。禁止以降低日志开销为理由绕过 Order HA quorum 或关闭 Replica ACK。

## 独立未完成项

- Order A/B/C ZK session 配置已预置为 15000ms、但现网仍是 6000ms。受控滚动变更被 `tests/order_ha_rollout_gate.py` 拦截，先处理 CPU/内存压力。
- Robot 50 个刷新间隔均为 1000ms、目标 20 档/tenant；`RobotWorker` 已实现报价匹配、稳定窗口及仅替换不匹配订单的逻辑，不应误称每个刷新周期都会撤换 2,000 单。
- Projection P232 / Order P054 仍需权威历史一致性核对；Tape 和 200 租户测试继续关闭。
