# Local candidate cohort, 2026-10-14

These are frozen local research candidates, **not qualified live strategies**.
Each `seed.json` is a local-backtest descriptor; its empty `javaSourceBase64`
intentionally prevents it from being submitted as a production import package.
Run `local_strategy_backtest.py` with the adjacent `GeneratedStrategy.java` via
`--source`. Do not fill in the source field or submit an import merely because
the Java source compiles.

The fixed window is 2025-10-13 through 2026-10-13. Validation-only research
used the scene-specific windows and withheld forward metrics. After source and
parameters were frozen, the production-equivalent local SIMSvr engine tested
the forward period exactly once per candidate. All three failed. Their forward
windows are consumed; no same-window parameter retry or renaming is allowed.

| Candidate | Scene | Validation-only reason to freeze | Formal trades | PF | Fee-adjusted validation | Fee-adjusted forward | Result |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| SOL higher-timeframe pullback short 2.0/4.0 | trend | 23 trades, PF 1.582 | 23 | 1.879 | 402.124 | -229.631 | OOS failed |
| ADA volume-weighted channel failure short 2.5/6.0 | channel | 29 trades, PF 1.376 | 28 | 1.849 | 461.461 | -11.558 | forward fee-adjusted PnL not positive |
| ETH volume-weighted channel failure long 2.0/4.0 | channel | 20 trades, PF 1.566 | 19 | 1.862 | 181.940 | -57.140 | too few trades; forward also negative |

The first parallel ETH run ended in an execution error and had no result; a
sequential rerun completed and produced the metrics above. Compilation and
execution success must not be confused with strategy qualification.
