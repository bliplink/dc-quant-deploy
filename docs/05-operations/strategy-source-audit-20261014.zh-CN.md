# 实盘策略源码完整性审计（2026-10-14）

## 结论

2026-10-14 10:12 UTC 的生产只读快照：100 条 ACTIVE，当前 v4 运行资格合格 9 条、不合格 91 条；9 条中仅 5 条满足另行计算的前瞻收益贡献比例。这与当天早些时候的快照一致。

对归档的 100 条实盘策略源码运行 `recovery/audit_strategy_seed.py`：93 条归档版本仍与当前 ACTIVE 版本相同，3 条已有较新 ACTIVE 版本，4 条归档名称已不在 ACTIVE 清单中。**在 93 条同版本源码中，没有发现 SHA-256 不一致或买卖方向、止损价、止盈价字段缺失。** 这次审计没有找到足以解释 91 条失格的确定性源码损坏，不能以“修复源码”为名直接重发。

另有 27 条归档策略的 `defaultParameters.momentumPeriod` 未被源码读取；2 条回归通道策略从源码读取 `atrPeriod` 和 `regressionPeriod`，但 `defaultParameters` 没有列出它们。后两者在源码调用中提供默认值，前者属于无效参数元数据。它们值得在后续重新生成时清理，但**不构成已证实的收益修复**，更不能仅修改元数据后将原策略算作新的独立合格策略。

## 复现

先用 `recovery/strategy_inventory_snapshot.py` 获取只读生产快照，然后执行：

```powershell
python recovery/audit_strategy_seed.py `
  --seed recovery/live-strategy-seed-current.json `
  --active-snapshot <快照目录>/active_strategy_qualification.tsv `
  --output <本地结果目录>/source_audit.json
```

审计脚本不连接服务器，不修改数据库，也不提交候选策略。归档版本与 ACTIVE 版本不同的条目必须先读取当前源码，不能拿旧源码结论推断新版本。源码审计只是完整性检查，不能替代生产等价回测、真实前瞻窗口或上线门槛。

本轮本地输出位于 `E:\sourcecode\codex\_work\strategy-inventory-100-snapshot-20261014-refresh\source_audit.json`，属于临时研究产物，不放入 Git。单元测试 `python -m unittest discover -s recovery -p 'test_audit_strategy_seed.py' -v` 为 3/3 通过。

## 对补齐 100 条的影响

现有缺口主要是策略的交易样本、OOS 和扣费后前瞻表现，而不是一批可批量修复的损坏源码。10 月 14 日已正式复核的五个新逻辑均未通过前瞻门槛；不能在同一前瞻窗口继续微调参数、改名或放宽门槛来凑数。下一批应先预注册真正不同的交易结构及参数范围，在验证段筛选后冻结源码，用未被该逻辑反复查看的前瞻数据做生产等价回测；只有完整通过者才提交服务器 `candidate.import`、生成、回测和自动发布核验。
