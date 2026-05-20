CREATE TABLE IF NOT EXISTS dc.chatgpt_analysis_ma20
(
    `analysis_time` DateTime,
    `symbol` String,
    `analysis_type` String,
    `image_logic` String,
    `latest_stage` String,
    `strategy` String,
    `strategy_type` String,
    `strategy_reason` String,
    `strategy_ext` String,
    `confidence` Float64,
    `image_path` String,
    `payload` String
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(analysis_time)
ORDER BY (symbol, analysis_time)
SETTINGS index_granularity = 8192;
