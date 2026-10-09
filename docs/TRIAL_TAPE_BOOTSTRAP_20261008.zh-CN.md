# Trial Tape 自动成交试点与验收（2026-10-08）

## 2026-10-09：所有新试用租户默认开启 Tape

- 新部署默认 `TRIAL_LIQUIDITY_TAPE_ENABLED=true`，`TRIAL_LIQUIDITY_TAPE_CANARY_LOCATION=`（空值）。所有**自动审批且通过安全检查的 TRIAL 租户**，在注册后依次创建独立 Tape 账户、幂等确认 Demo 入金、启动 Maker 20+20 与 Tape 主动 IOC。普通正式 ACTIVE 租户不走 Trial Bootstrap，不允许借此自动入金。
- 若需要故障隔离，可设置 `TRIAL_LIQUIDITY_TAPE_ENABLED=false` 或限定 `TRIAL_LIQUIDITY_TAPE_CANARY_LOCATION=<LOCATION>`；这只影响尚未经过 `REVOKE_CASH` 的新 Bootstrap，**不会自动关闭已经启用的 Tape 机器人**。停用现有机器需使用租户 Robot 管理接口。
- 之前 `COMPLETE/DONE` 的 Maker-only 租户**不会因为默认开关改变而自动补建账户**。升级时，在已经确认全部 Robot 健康、Projection 水位一致后逐个执行 `tests/run-trial-tape-canary-host.sh`，提供每个租户明确的 `TAPE_CANARY_LOCATION`、`TAPE_CANARY_CONFIRM` 和 `TAPE_CANARY_APPLY=YES`；新版脚本允许当前全局灰度限制为空。脚本只排队该租户的 `REVOKE_CASH` 后续步骤，不重复 Maker 入金，不能对未确认 Tape 入金的任务重置回放。
- 单实例 Mac mini 8核/16GiB 环境仍需逐批验收 10→50→100→200 租户，观测 CPU PSI、内存、撮合 TPS、Trade/Order 分区延迟、Projection 水位。**默认开启不代表 200 个租户压测已经通过**。
- Tape Demo=1 的 IOC 成交需要同时以 MDSvr `recentTrades` 最新成交、Tape 用户 `dc_users_posting` 中 `source='Trade'` 的增长、持仓与资金一致性核验；`dc_orders_execorders` 不一定包含这些内部 Demo 成交。使用 `tests/verify-trial-tape-live-host.py` 做时间窗只读验收。

目标：试用 tenant 自动审批后保留 Maker 20+20 档，并可为指定租户启用 Binance aggTrade 模拟成交量主动点价。真实币安对冲仍关闭，不涉及真实资产。

- `TRIAL_LIQUIDITY_TAPE_ENABLED=false` 默认为关闭；`TRIAL_LIQUIDITY_TAPE_CANARY_LOCATION=<LOCATION>` 限制在一个租户。只有 `REVOKE_CASH` 状态被处理时才写入持久化的 `tape_enabled=1`，随后该决定不受环境变化影响。
- 自动状态机：`CREATE_MAKER → CREATE_KEY → FUND → REVOKE_CASH → CREATE_TAPE → CREATE_TAPE_KEY → FUND_TAPE → REVOKE_TAPE_CASH → CREATE_ROBOT → ENABLE → VERIFY`。
- Tape 使用独立内部用户和交易 API Key；Demo 资金默认上限 10000 USDT，独立 HMAC 密码；内置策略 `tape_volume_scale=0.01`、`tape_max_notional=100`、`tape_min_notional=5`、`tape_interval_ms=1000`。可通过租户 Liquidity Profile 热更新调整。
- Tape 入金在发出 cashIn 前先提交 `TAPE_FUND_IN_FLIGHT`，结果未知一律进入 `NEEDS_RECONCILIATION`，绝不自动二次入金。只在 confirmed 后才能启用 Tape 策略。Maker 原有入金逻辑不变。
- 已完成的既有 50 个租户不会因镜像升级自动变更。**仅在检查独立 AdminSvr 正式镜像、数据库迁移和环境开关以后**，可在单一原先 Maker-only 的 `COMPLETE` 试用租户上执行灰度：

```bash
export ENV_FILE=/path/to/fresh2.env
export TAPE_CANARY_LOCATION=<LOCATION>
export TAPE_CANARY_CONFIRM=<LOCATION>
export TAPE_CANARY_APPLY=YES
bash tests/run-trial-tape-canary-host.sh
```

这只将已完成 job 从 `DONE` 重排到 `REVOKE_CASH`，由 AdminSvr 重新进入 Tape 专用步骤，**不会**重复 maker 创建/入金，也不会停止共享 RobotSvr。

脚本先核验**所有已启用 Robot 均为近期心跳正常的 RUNNING 且仍有真实挂单**，任何一个因 Trade 分区恢复进入 ERROR/DEGRADED 都会阻断试点。这是对外 Demo 共享环境的强制安全门禁。

验收：观察该 tenant 的 Bootstrap=COMPLETE、Tape user/key 存在且为不同 user、Tape cashIn 恰好一次、Maker/Tape 的 `enable_cash_in=0`、Robot `RUNNING`、盘口 10+10、最近成交源于 `RobotSvr-Tape` 且实际在 MySQL `dc_orders_execorders` 与资金流水中对账。然后比较其他 tenant 的 10+10 可见盘口、Robot health、Order/Trade/MD/GW 重启/OOM、CPU/内存。失败时暂停该租户 Tape 参数或禁用其 Robot，保留账务取证，不自动重试不确定资金。

扩容严格按 1 → 5 → 10 → 50，并在不同负载下重新做 TPS、P95/P99 和宕机恢复，不得直接据 50 个仅挂单 Robot 的容量结论推断 50 个 Tape 的能力。
