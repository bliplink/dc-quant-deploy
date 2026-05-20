CREATE TABLE IF NOT EXISTS dc.strategy_review_fact
(
    `id` String,
    `trade_date` Date32,
    `strategy_name` LowCardinality(String),
    `strategy_version` String,
    `symbol` String,
    `text` String,
    `scene` LowCardinality(String),
    `fact_type` LowCardinality(String),
    `severity` UInt8,
    `evidence` String,
    `review_report_path` String,
    `payload` String
)
ENGINE = MergeTree
ORDER BY (trade_date, strategy_name, strategy_version, symbol, text, fact_type)
SETTINGS index_granularity = 8192;
