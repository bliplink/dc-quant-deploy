CREATE TABLE IF NOT EXISTS dc.backtest_optimization_trial
(
    `run_time` DateTime CODEC(LZ4),
    `sid` String CODEC(LZ4),
    `strategy_name` String CODEC(LZ4),
    `strategy_version` String CODEC(LZ4),
    `symbol_scope` String CODEC(LZ4),
    `text_scope` String CODEC(LZ4),
    `trial_no` Int32 CODEC(LZ4),
    `phase` String CODEC(LZ4),
    `param_set` String CODEC(LZ4),
    `fit_pnl` Float64 CODEC(LZ4),
    `validate_pnl` Float64 CODEC(LZ4),
    `forward_pnl` Float64 CODEC(LZ4),
    `total_pnl` Float64 CODEC(LZ4),
    `forward_score` Float64 CODEC(LZ4),
    `max_drawdown_pct` Float64 CODEC(LZ4),
    `overfit_pass` Int8 CODEC(LZ4),
    `overfit_reason` String CODEC(LZ4),
    `rank` Int32 CODEC(LZ4),
    `elapsed_ms` Int32,
    `symbol_count` Int32,
    `slice_count` Int32,
    `fit_window_days` Int32,
    `validate_window_days` Int32,
    `forward_window_days` Int32,
    `min_slice_count` Int32,
    `optimization_objective` String,
    `min_forward_contribution` Float64,
    `fragile_best` Int8,
    `stable_param_range` String,
    `neighbor_avg_pnl` Float64,
    `neighbor_worst_pnl` Float64,
    `payload` String CODEC(LZ4)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(run_time)
ORDER BY (strategy_name, strategy_version, sid, trial_no)
SETTINGS index_granularity = 8192;
