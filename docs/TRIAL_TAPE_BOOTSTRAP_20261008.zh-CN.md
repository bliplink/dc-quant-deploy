# Trial Tape 自动成交试点与验收（2026-10-08）

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
