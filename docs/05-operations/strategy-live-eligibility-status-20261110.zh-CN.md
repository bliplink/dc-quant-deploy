# 实盘登记状态与运行资格一致性修复（2026-11-10）

## 问题与证据

126 量化主机的 INDSvr `latest` 镜像修复前 revision 为 `cb6472b1ec2e8581dcdf22eabb1ed11f4b996cfc`。实盘列表直接显示 `strategy_live_registry.status`，而场景候选选择和策略版本运行闸门还会调用 `StrategyBacktestQualificationService`。因此登记为 ACTIVE 不代表能够参与运行。

2026-11-10 03:39～03:48 UTC 的服务器审核与数据库只读查询一致：登记 ACTIVE 100 条，当前运行资格通过 4 条，失败 96 条。失败分布为 OOS 67、交易样本不足 23、前瞻扣费收益非正 4、验证扣费收益非正 1、PF 不足 1。此前早晨快照为 5 条合格；运行中的每日复核更新了证据，不能把旧快照当作固定库存。

资格闸门是既有机制，不是当天本地候选回测新增的限制。实际运行配置为 v4 非重叠滚动回测、证据最近 45 天、交易至少 20 笔、PF 至少 1.20、最大回撤 15%，并要求 OOS 及扣费验证/前瞻收益通过。不得关闭或放宽这些配置来让登记数量看似达标。

## 安全修复

用户要求将实际不可用策略下线，保留合格策略、历史和失败原因。原 `dc.ind.workbench.live.strategy.offline` 默认同时发布平仓信号；系统仍有持仓记录，不能把状态纠正变成批量强平。

INDSvr 增加兼容选项：

- `closePositions=false`：只下线登记，不发布平仓信号，不撤单，不改仓位或风控配置；未传时维持原有下线并发平仓信号行为。
- `strategyVersion`：精确版本退休，数据库更新谓词也包含版本，不能误下线并发发布的新版本。
- `requireIneligible=true`：服务端再次刷新资格，拒绝下线已合格或证据缺失的策略。
- 状态纠正必须精确给出策略名、版本、单品种和周期；响应为 `offlineExecutionStatus=status_only`、`closeSignalCount=0`，仍写正式 OFFLINE 发布事件。

本次操作不扩大到“当前场景暂时没被选中”的合格策略；市场场景暂不匹配不等于策略应该永久下线。

## 执行与恢复

工具：`recovery/reconcile_live_strategy_eligibility.py`，默认只读。凭据仅由进程环境变量 `STC_PROD_KEY_PASSPHRASE` 注入。使用已登记 SSH host key、126 的 `ec2-user` 和量化 GW 31002，不操作旧系统的 3002。

```powershell
python -m recovery.reconcile_live_strategy_eligibility --output-dir <本机证据目录>
python -m recovery.reconcile_live_strategy_eligibility --output-dir <同一目录> --apply --expected-plan-sha256 <只读阶段输出的哈希>
```

执行前校验服务器实际资格配置与计划一致、运行服务审核与数据库统计一致。先对不存在的策略做无修改能力探测，确认新服务认识 status-only 参数；旧服务会忽略新参数，因此未验证能力绝不能发送真实目标。

每条下线只请求一次，保存请求、结果和检查点。超时/中断必须先核对服务端状态，不得盲重试；完成后等待 ClickHouse mutation 真正完成，重新核对 ACTIVE、运行资格及 Web 实盘列表 API 数量。完整注册表备份只保存在本机证据目录，不提交生产数据和密钥。

本次证据目录：`E:\sourcecode\codex\_work\strategy-live-eligibility-offline-20261110`。最终结果以其 `summary.json`、`after/runtime-audit.json` 和 `after/ui-active-list.json` 为准；计划冻结或接口修复完成均不等于生产下线完成。

补充策略回测在独立进程继续，不因下线把候选或失败版本计作新实盘策略。完成目标仍为 100 条真正合格、逻辑独立的实盘库存。
