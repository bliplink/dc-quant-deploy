CREATE TABLE IF NOT EXISTS dc.strategy_review_fact
(
    `id` String,
    `trade_date` Date32 CODEC(LZ4),
    `strategy_name` String CODEC(LZ4),
    `strategy_version` String CODEC(LZ4),
    `symbol` String CODEC(LZ4),
    `text` String CODEC(LZ4),
    `scene` String CODEC(LZ4),
    `fact_type` String CODEC(LZ4),
    `severity` UInt8 CODEC(LZ4),
    `evidence` String CODEC(LZ4),
    `review_report_path` String CODEC(LZ4),
    `payload` String CODEC(LZ4)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(trade_date)
ORDER BY (strategy_name, strategy_version, trade_date, symbol, text, fact_type)
SETTINGS index_granularity = 8192;
