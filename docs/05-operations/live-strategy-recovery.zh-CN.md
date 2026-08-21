# 实盘策略备份与恢复

本流程用于新环境或灾难恢复。它只备份当前 `ACTIVE` 实盘策略，并坚持以下安全边界：

- 不直接写 `strategy_live_registry`。
- 不调用 `dc.ind.workbench.live.strategy.backup.restore`。
- 恢复统一调用 `dc.ind.strategy.candidate.import`。
- 每条策略必须重新编译、执行正式场景回测，并通过当前自动发布门槛后才能进入实盘。
- 旧环境的 JAR 只作为完整性备份，恢复时不直接加载，避免绕过新环境编译和资格校验。

## 备份

在部署目录执行：

```bash
sudo ./backup-live-strategies.sh
```

默认输出到：

```text
/data/strategy/data/indsvr/backup/live-strategy-seed-current.json
```

备份会校验每条 ACTIVE 策略都具备 Java 源码，并保存源码、参数、场景、品种、原版本与原 JAR。任何 ACTIVE 策略缺少源码时，整个备份失败，不生成不完整种子。

## 恢复前检查

部署新环境并确认以下条件满足：

- INDSvr、SIMSvr、ClickHouse、GW 正常。
- 10 个品种的 `15m/1h/1d` K 线与历史场景数据完整。
- 当前正式场景回测和自动发布门槛已经启用。

先执行 dry-run：

```bash
sudo ./restore-live-strategies.sh recovery/live-strategy-seed-current.json --dry-run
```

dry-run 只检查备份和当前环境状态，不提交候选。已存在的 ACTIVE 策略或已有候选会显示为 `SKIP`。

## 正式恢复

```bash
sudo ./restore-live-strategies.sh recovery/live-strategy-seed-current.json
```

脚本默认串行恢复，逐条等待正式回测终态。结果分为：

- `PUBLISHED`：编译、正式场景回测和自动发布全部通过。
- `BACKTEST_SUCCESS_NOT_PUBLISHED`：回测完成，但未通过自动发布门槛，不会强行上线。
- `FAILED`：生成、编译或回测失败。
- `SKIP ACTIVE`：目标环境已经存在同名 ACTIVE 策略。
- `SKIP EXISTING`：目标环境已有同名候选，避免重复提交。

可先用 `--limit 1` 在新环境验收一条，再执行完整恢复：

```bash
sudo ./restore-live-strategies.sh recovery/live-strategy-seed-current.json --limit 1
```

恢复结果不会保证所有历史策略重新上线；不能通过当前正式资格门槛的策略应保持未发布，这正是灾难恢复仍需重验收的目的。
