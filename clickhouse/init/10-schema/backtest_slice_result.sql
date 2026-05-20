CREATE TABLE IF NOT EXISTS dc.backtest_slice_result
(
    `run_time` DateTime,
    `sid` String,
    `strategy_name` String,
    `strategy_version` String,
    `symbol` String,
    `text` String,
    `slice_no` Int32,
    `fit_begin` String,
    `fit_end` String,
    `validate_begin` String,
    `validate_end` String,
    `forward_begin` String,
    `forward_end` String,
    `fit_pnl` Float64,
    `validate_pnl` Float64,
    `forward_pnl` Float64,
    `fit_trade_count` Int32,
    `validate_trade_count` Int32,
    `forward_trade_count` Int32,
    `fit_max_drawdown_pct` Float64,
    `validate_max_drawdown_pct` Float64,
    `forward_max_drawdown_pct` Float64,
    `payload` String
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(run_time)
ORDER BY (strategy_name, strategy_version, run_time, symbol, text, slice_no)
SETTINGS index_granularity = 8192;
