# 本机历史场景标签任务（2026-10-15）

## 范围与边界

用户批准了本机生成及抽检，**未批准写入 126 数据库或发布策略**。目标是 10 个品种在 UTC 2024-12-01 至 2025-08-11 的 00:00/12:00 标签，共 5,080 条。按 10 天、单品种切分为 260 块。现有 2025-08-12 至 2025-10-12 的规范场景数据每品种 124 条，仅在本机拼接。

运行器 `recovery/run_local_historical_scene_campaign.py` 固定 `--export-rows-only --kline-dir`、`-Duser.timezone=UTC`，并将 ClickHouse URL 指向不可用的本机 `127.0.0.1:9`。每块必须验证 12 小时点位、`SUCCESS`、`historical_kline_scene`、prompt 版本、`local_codex` provider 和指定模型；通过后记录 SHA-256 检查点。失败停在原块并保留日志；只有查清后才使用 `--retry-failed`。不能把 checkpoint 数量等同于策略通过数。

本机输入为 `E:\sourcecode\codex\_work\strategy-research-input-20261015-older`，任务输出为 `E:\sourcecode\codex\_work\strategy-scene-campaign-20261015`。2026-10-15 14:30（上海时间）启动了隐藏后台进程；PID 仅供当次排查，是否仍运行应以进程及日志核对。进度看 `status.json`，标准输出/错误看 `campaign.stdout.log` / `campaign.stderr.log`，每块日志看 `chunks/<symbol>/<date-range>/attempt_*/runner.log`。任务可用原参数重复执行，已校验块自动跳过：

```powershell
python -u -m recovery.run_local_historical_scene_campaign `
  --input-dir E:\sourcecode\codex\_work\strategy-research-input-20261015-older `
  --output-dir E:\sourcecode\codex\_work\strategy-scene-campaign-20261015 `
  --indsvr-repo E:\sourcecode\stc\com.app.dc.indsvr `
  --begin 2024-12-01 --end 2025-08-11 --chunk-days 10 --timeout-minutes 15
```

`recovery/assemble_local_historical_scene_input.py` 只在全部 260 块的检查点、文件哈希和时间点校验通过，并且现有场景 12 小时点位完整时，才把规范 K 线与两段标签写入 `strategy-research-input-20261015-extended`。它先在 `.assembling` 目录生成，最后才原子重命名，并写 `READY.json`；任何未齐全批次都会拒绝生成。因此下游研究只可读取带 `READY.json` 的最终目录：

```powershell
python -m recovery.assemble_local_historical_scene_input `
  --input-dir E:\sourcecode\codex\_work\strategy-research-input-20261015-older `
  --campaign-dir E:\sourcecode\codex\_work\strategy-scene-campaign-20261015 `
  --output-dir E:\sourcecode\codex\_work\strategy-research-input-20261015-extended
```

当前批次未完时，上述命令已实测在缺失的 ADA 2024-12-11 至 12-20 检查点处拒绝，**没有创建扩展输入目录**。相关 Python 合同测试共 12 项通过。生成完成后仍需抽检跨品种/日期的标签质量、复核无未来信息，再按独立的研究验证与 SIMSvr 正式回测门槛筛选；不能据此宣布 91 个策略合格。
