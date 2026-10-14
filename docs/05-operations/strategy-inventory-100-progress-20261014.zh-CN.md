# 100 条实盘策略补齐进度（2026-10-14）

## 当前结论

生产 `strategy_live_registry` 有 100 条 ACTIVE，但按 INDSvr 当前 v4 运行时资格口径，仅 9 条合格，91 条不合格：OOS 失败 56、交易数不足 28、PF 不足 4、前瞻扣费后不盈利 3。快照明细在 `recovery/snapshots/strategy-inventory-100-20261014/`，可用 `recovery/strategy_inventory_snapshot.py` 重新只读生成。

这 9 条中，按 SIMSvr 自动发布另行要求的 `fee_adjusted_forward_pnl / total_pnl >= min_forward_contribution (0.20)` 估算，仅 5 条通过。其余 4 条是 BTC trend、SOL trend、UNI range 的旧版本和 UNI range v5。这个 5 只是前瞻贡献维度的复核，不等于完整自动发布决策；还需考虑基线比较、重复逻辑等。当前运行时资格检查与自动发布门槛并不完全一致，不能把 9 直接称作“达到全部上线标准”。**本轮没有改动运行时准入门槛，也没有下线任何已有策略。**

另有 9 个最新回测结果满足当前运行时资格、但对应版本没有 ACTIVE 注册：有的为 `live_recheck`，有的在自动发布时因前瞻贡献不足而 `SKIP`，还包含同一 UNI/DOGE 逻辑的重复版本。不能直接注册这 9 个来凑数量。

短期失效的实例：`lcr1_xrp_cha_c10143d0@v6` 在 10 月 13 日正式回测为 23 笔、PF 2.145、前瞻扣费后 +295.056 并发布；10 月 14 日滚动窗口复核变为 18 笔、前瞻扣费后 -51.033，虽然注册表仍标记 ACTIVE，当前资格已失效。因此补齐 100 不能只是一次性发布，还必须持续复核、及时剔除失效库存。

目标“每个 10 品种 × 5 场景有 2 条独立合格策略”与表面上的 ACTIVE=100 不是同一指标：截至本轮，50 个格子里 48 个未满 2 条。一个逻辑家族的相邻止损/止盈参数不能算作多条独立策略。

## 本轮本机研究与正式引擎复核

固定研究窗口 `2025-10-13` 至 `2026-10-13`，从生产 ClickHouse 只读导出 10 品种 15 分钟 K 线及场景标签到本机 `_work/strategy-research-input-20261014`。研究预筛仅使用验证段；前瞻段在候选冻结前不计算、不展示。修正了旧 `StrategyResearchBatchCli` 把所有场景都当作 120/30/14 的问题，现与生产一致：range 90/30/14，breakout/reversal 120/20/10，其它 120/30/14。修正前的 range、breakout、reversal 结果作废。

修正后的定向预筛共 920 个“品种 × 假设参数”组合：range 60、breakout 180、reversal 500、trend 60、channel 120。前 3 组通过数均为 0；trend 通过 5 个参数组合，集中在 LINK/SOL 的同一家族；channel 通过 5 个参数组合，集中在 BNB、SOL、XRP 三个家族/品种格子。这里只是粗筛，不等于 10 条可上线策略。

从预筛结果冻结源码和参数后，使用本机 `LocalBacktestCli`、生产 SIMSvr 引擎和 SSH 只读 ClickHouse 通道做了 5 个正式等价试点，结果如下。它们均未提交生产 `candidate.import`，也未发布：

| 固定假设 / 品种 | 交易数 | PF | 验证扣费后 PnL | 前瞻扣费后 PnL | 结果 |
| --- | ---: | ---: | ---: | ---: | --- |
| HMA/VWMA short / LINK | 52 | 1.456 | 308.955 | -404.755 | OOS 失败 |
| HMA/VWMA short / SOL | 74 | 1.592 | 776.518 | -284.104 | OOS 失败 |
| Donchian close-location fade short / BNB | 22 | 1.632 | 138.090 | -88.818 | OOS 失败 |
| ATR envelope two-bar reentry long / SOL | 20 | 2.772 | 518.029 | -28.003 | 前瞻扣费后不盈利 |
| ATR envelope two-bar reentry long / XRP | 30 | 1.724 | 191.933 | -108.561 | OOS 失败 |

这 5 条已经看过当前前瞻段，**不得再对同一窗口做参数微调、重新命名并提交**。若继续研究，必须提出真正不同的结构假设，并用新的未见样本或预注册的下一时间窗口做最终检验。不能降低交易数、PF、OOS、费用或前瞻贡献门槛来凑 100。

本机正式结果保存在 `E:\sourcecode\codex\_work\strategy-local-formal-20261014`；预筛结果及每次输入 K 线 SHA-256 保存在 `E:\sourcecode\codex\_work\strategy-local-validation-20261014`。它们是本机生成物，不在 Git 跟踪。脚本在本仓库 `recovery/` 下，可跨会话复用，私钥口令仅从进程环境变量读取。

INDSvr 的研究 CLI 场景窗口与前瞻隔离修正位于远端独立分支 `codex/strategy-inventory-100-20261014`，提交 `bb79e8f`；未合并到 `latest`，因此不会因本轮研究触发生产 INDSvr 升级。继续开发时先拉取该分支，再决定是否将测试工具改动并入主线。

## 后续执行顺序

1. 先以 `strategy_inventory_snapshot.py` 刷新 91 条和 50 格缺口，锁定本次研究窗口与行情 SHA-256；不要把旧快照的合格数当实时值。
2. 对未测试的独立逻辑家族预注册假设与参数范围，用 `run_local_strategy_validation.py` 做只看验证段的粗筛。该脚本的研究模拟器不是 SIMSvr；它的 `accepted=YES` **绝不是上线许可**。
3. 把每个家族只保留少量代表逻辑，移植为可编译 Java 策略，用 `local_strategy_backtest.py` 调本机生产等价引擎。必须使用与拟提交 `candidate.import` 相同的源码、参数、品种、场景和窗口。
4. 仅对本机完整通过且无重复指纹、无不合理集中风险的候选提交生产 `candidate.import`；观察 generation task、candidate、backtest task、backtest result、auto-publish decision 和 live registry。异步接口的 `accepted` 不表示回测通过。
5. 发布后重新审计 ACTIVE、当前 v4 资格、前瞻贡献、每格独立逻辑数量和实盘信号。单纯把 ACTIVE 行数补到 100 不算完成。

## 验证

- `StrategyResearchBatchCliTest`：19/19 通过，包括场景窗口与源码模板验证。
- `recovery` Python 单元测试：7/7 通过；新增脚本通过 `py_compile`。
- 生产侧仅执行 SSH/ClickHouse/GW 只读查询和历史数据导出；没有写生产数据库、下单或发布策略。
