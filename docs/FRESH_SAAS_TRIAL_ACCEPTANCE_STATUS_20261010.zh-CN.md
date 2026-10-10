# 干净重建后 Trial / Tape / 租户压测的实际验收状态（2026-10-10）

**环境：** Mac mini + Colima，原 Demo 已使用新数据目录完成冷重建；安装器确认 24/24 容器启动，Order/Trade 256/256 分区 READY，本机四个 Web 端口和主站、Trade Web、API Docs 公网 HTTPS 返回 200。此状态不代表已执行真实订单故障注入。

## 已完成

- `dc-quant-deploy` [de623f6](https://github.com/bliplink/dc-quant-deploy/commit/de623f679b8a3cd4200b8dfc1c217079c8b960fc) 修复 `deploy-saas.sh` 在缺少 Tape 开关时错误写入 `TRIAL_LIQUIDITY_TAPE_ENABLED=false` 的问题；现在与 `.env.example` 和 Compose 的默认 `true` 保持一致，保留运维人员显式覆盖的能力。
- 实际 Mac 私有候选部署环境已设为 `TRIAL_LIQUIDITY_TAPE_ENABLED=true`，**只重建 AdminSvr** 并通过运行中容器环境检查；三个 OrderSvr A/B/C 未重启。`TRIAL_LIQUIDITY_BOOTSTRAP_ENABLED=true`、`TRIAL_LIQUIDITY_DEMO_RETRY_ENABLED=true`，Tape canary 为空（意味着不限制租户位置），主密钥仅检查已配置且绝不在文档或日志中输出。
- Trial 自动引导的后台 Worker 使用持久化阶段状态机，Tape 账户独立于 maker，真实现金请求结果不明确时不执行盲目重试。现有 `TrialLiquidityBootstrapWorkerTest` Maven 离线执行通过；代码只会在租户确属已批准的 TRIAL 且完成前提检查后推进机器人初始化。
- `tests/check-tenant-ramp-readiness.py` 的新鲜空库由笼统 `TELEMETRY_UNAVAILABLE` 改为具体 `MARKET_ACTIVITY_BASELINE_EMPTY`，真实只读检查返回 `gate=NOT_READY`, `nextRampAuthorized=false`；13 项离线测试通过，其他监控故障仍是 `TELEMETRY_UNAVAILABLE`，不构成放宽门禁。

## 仍未验收 / 不能宣称成功

- 新 MySQL 的 `dc_tenant=0`、`dc_tenant_robot=0`；因此未验证自动注册、租户独立 Tape 实际入金/点价、盘口报价、真实 Trader API Key 余额/下单/撤单，以及 Broker 委托交易和客户隔离。
- `tests/run-tenant-lifecycle-e2e-host.sh` 会在创建任何账号前验证 Java Broker Runner 所属 RobotSvr 的**已审核不可变镜像 ID**。当前运行 RobotSvr `sha-5941ee...` 不在审核清单；验证返回 `BLOCKED_UNREVIEWED_BROKER_RUNNER`。严禁为通过验收而绕过白名单或手动伪造数据库下单；正式镜像需按 Broker 资金/订单清理与跨租户拒绝语义完成审核，或按照既有已审核隔离 Runner 流程执行。
- 200 租户阶梯压测 **尚未开始**。应先验证至少一个隔离租户的完整 Robot、主动点价和权威订单持仓资金流水，再逐级 10/25/50/100/200 租户观测 CPU、IO、延迟、GC、ZooKeeper 会话、Order 三副本、Projection 水位；禁用盲目连续批量创建。
- 旧 P246 故障证据单独保留，但新环境 256/256 READY 不能证明**历史缺口归档恢复、跨 epoch 晋升或日志自动安全删除**；Order 完整写入排空/跨节点迁移及 WAL GC 仍是待实现或待验收项。

**下一个可执行门禁：** 正式完成 Broker Runner 镜像身份及代码审核，允许在隔离环境运行有权威清理和资金对账的交易验收，再以只读资源监控决定是否开始小批量租户压测。即使基础部署成功，也不能把新环境 0 租户的 `NOT_READY` 误报为系统承载能力结论。
