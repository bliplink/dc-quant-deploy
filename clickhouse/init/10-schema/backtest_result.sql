CREATE TABLE IF NOT EXISTS dc.backtest_result
(
    `run_time` DateTime CODEC(LZ4),
    `sid` String CODEC(LZ4),
    `strategy_name` String CODEC(LZ4),
    `strategy_version` String CODEC(LZ4),
    `baseline_version` String CODEC(LZ4),
    `runtime_type` String CODEC(LZ4),
    `scene` String CODEC(LZ4),
    `symbol` String CODEC(LZ4),
    `text` String CODEC(LZ4),
    `begin_date` String CODEC(LZ4),
    `end_date` String CODEC(LZ4),
    `trade_count` Int32 CODEC(LZ4),
    `win_count` Int32 CODEC(LZ4),
    `loss_count` Int32 CODEC(LZ4),
    `flat_count` Int32 CODEC(LZ4),
    `win_rate` Float64 CODEC(LZ4),
    `total_return_pct` Float64 CODEC(LZ4),
    `max_drawdown_pct` Float64 CODEC(LZ4),
    `initial_capital` Float64 CODEC(LZ4),
    `final_capital` Float64 CODEC(LZ4),
    `total_pnl` Float64 CODEC(LZ4),
    `forward_score` Float64 CODEC(LZ4),
    `window_mode` String CODEC(LZ4),
    `slice_count` Int32 CODEC(LZ4),
    `fit_pnl` Float64 CODEC(LZ4),
    `validate_pnl` Float64 CODEC(LZ4),
    `forward_pnl` Float64 CODEC(LZ4),
    `overfit_pass` Int8 CODEC(LZ4),
    `overfit_reason` String CODEC(LZ4),
    `optimization_mode` String CODEC(LZ4),
    `trial_count` Int32 CODEC(LZ4),
    `best_param_set` String CODEC(LZ4),
    `best_rank` Int32 CODEC(LZ4),
    `symbol_count` Int32 CODEC(LZ4),
    `fit_window_days` Int32 CODEC(LZ4),
    `validate_window_days` Int32 CODEC(LZ4),
    `forward_window_days` Int32 CODEC(LZ4),
    `min_slice_count` Int32 CODEC(LZ4),
    `optimization_objective` String CODEC(LZ4),
    `min_forward_contribution` Float64 CODEC(LZ4),
    `elapsed_ms` Int32 CODEC(LZ4),
    `fragile_best` Int8 CODEC(LZ4),
    `stable_param_range` String CODEC(LZ4),
    `neighbor_avg_pnl` Float64 CODEC(LZ4),
    `neighbor_worst_pnl` Float64 CODEC(LZ4),
    `report_path` String CODEC(LZ4),
    `payload` String CODEC(LZ4)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(run_time)
ORDER BY (strategy_name, strategy_version, run_time, symbol, text)
SETTINGS index_granularity = 8192;

ALTER TABLE dc.backtest_result ADD COLUMN IF NOT EXISTS optimization_mode String AFTER overfit_reason;
ALTER TABLE dc.backtest_result ADD COLUMN IF NOT EXISTS trial_count Int32 AFTER optimization_mode;
ALTER TABLE dc.backtest_result ADD COLUMN IF NOT EXISTS best_param_set String AFTER trial_count;
ALTER TABLE dc.backtest_result ADD COLUMN IF NOT EXISTS best_rank Int32 AFTER best_param_set;
ALTER TABLE dc.backtest_result ADD COLUMN IF NOT EXISTS symbol_count Int32 AFTER best_rank;
ALTER TABLE dc.backtest_result ADD COLUMN IF NOT EXISTS fit_window_days Int32 AFTER symbol_count;
ALTER TABLE dc.backtest_result ADD COLUMN IF NOT EXISTS validate_window_days Int32 AFTER fit_window_days;
ALTER TABLE dc.backtest_result ADD COLUMN IF NOT EXISTS forward_window_days Int32 AFTER validate_window_days;
ALTER TABLE dc.backtest_result ADD COLUMN IF NOT EXISTS min_slice_count Int32 AFTER forward_window_days;
ALTER TABLE dc.backtest_result ADD COLUMN IF NOT EXISTS optimization_objective String AFTER min_slice_count;
ALTER TABLE dc.backtest_result ADD COLUMN IF NOT EXISTS min_forward_contribution Float64 AFTER optimization_objective;
ALTER TABLE dc.backtest_result ADD COLUMN IF NOT EXISTS elapsed_ms Int32 AFTER min_forward_contribution;
ALTER TABLE dc.backtest_result ADD COLUMN IF NOT EXISTS fragile_best Int8 AFTER elapsed_ms;
ALTER TABLE dc.backtest_result ADD COLUMN IF NOT EXISTS stable_param_range String AFTER fragile_best;
ALTER TABLE dc.backtest_result ADD COLUMN IF NOT EXISTS neighbor_avg_pnl Float64 AFTER stable_param_range;
ALTER TABLE dc.backtest_result ADD COLUMN IF NOT EXISTS neighbor_worst_pnl Float64 AFTER neighbor_avg_pnl;
