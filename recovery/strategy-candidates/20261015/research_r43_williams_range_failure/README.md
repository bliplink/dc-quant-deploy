# Frozen round43 research, not for release

ADA long and XRP short share the Williams %R20 range-failure logic in `GeneratedStrategy.java`. The two `seed.json` entries freeze ATR14 stop 2.0 / take 4.0 before the first formal backtest. Source SHA-256: `9453712D13D5D5F0799EA86B8DE6D290981ACC1A1F55DE87B12434E212FE2478`.

Both failed the local SIMSvr v4 forward test on 2026-10-15 (`oos_not_passed`); neither was imported or published. Do not retune these hypotheses against the same forward window. See `docs/05-operations/strategy-research-parity-20261015.zh-CN.md`. `javaSourceBase64` is intentionally empty to prevent accidental import.
