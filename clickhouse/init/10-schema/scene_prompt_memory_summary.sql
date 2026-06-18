CREATE TABLE IF NOT EXISTS dc.scene_prompt_memory_summary
(
    `id` String,
    `symbol` String DEFAULT '',
    `timeframe` LowCardinality(String) DEFAULT '15m',
    `time_range_days` UInt16 DEFAULT 30,
    `top_scene_failures_json` String DEFAULT '',
    `top_scene_success_patterns_json` String DEFAULT '',
    `no_trade_pressure_score` Float64 DEFAULT 0,
    `flip_pressure_score` Float64 DEFAULT 0,
    `summary_text` String DEFAULT '',
    `update_time` DateTime
)
ENGINE = ReplacingMergeTree(update_time)
ORDER BY (symbol, timeframe, time_range_days, id)
SETTINGS index_granularity = 8192;
