CREATE TABLE IF NOT EXISTS dc.backtest_slice_result
(
    `run_time` DateTime CODEC(LZ4),
    `sid` String CODEC(LZ4),
    `strategy_name` String CODEC(LZ4),
    `strategy_version` String CODEC(LZ4),
    `symbol` String CODEC(LZ4),
    `text` String CODEC(LZ4),
    `slice_no` Int32 CODEC(LZ4),
    `fit_begin` String CODEC(LZ4),
    `fit_end` String CODEC(LZ4),
    `validate_begin` String CODEC(LZ4),
    `validate_end` String CODEC(LZ4),
    `forward_begin` String CODEC(LZ4),
    `forward_end` String CODEC(LZ4),
    `fit_pnl` Float64 CODEC(LZ4),
    `validate_pnl` Float64 CODEC(LZ4),
    `forward_pnl` Float64 CODEC(LZ4),
    `fit_trade_count` Int32 CODEC(LZ4),
    `validate_trade_count` Int32 CODEC(LZ4),
    `forward_trade_count` Int32 CODEC(LZ4),
    `fit_max_drawdown_pct` Float64 CODEC(LZ4),
    `validate_max_drawdown_pct` Float64 CODEC(LZ4),
    `forward_max_drawdown_pct` Float64 CODEC(LZ4),
    `payload` String CODEC(LZ4)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(run_time)
ORDER BY (strategy_name, strategy_version, run_time, symbol, text, slice_no)
SETTINGS index_granularity = 8192;
