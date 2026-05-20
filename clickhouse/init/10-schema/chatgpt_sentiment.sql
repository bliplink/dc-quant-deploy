CREATE TABLE IF NOT EXISTS dc.chatgpt_sentiment
(
    `analysis_time` DateTime,
    `symbol` String,
    `analysis_type` String,
    `sentiment` String,
    `risk_level` String,
    `risk_action` String,
    `event_focus` String,
    `summary` String,
    `confidence` Float64,
    `source_urls` String,
    `payload` String
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(analysis_time)
ORDER BY (symbol, analysis_time)
SETTINGS index_granularity = 8192
COMMENT 'AI分析市场热点记录表';
