CREATE TABLE IF NOT EXISTS dc.strategy_release_event
(
    `id` String,
    `event_time` DateTime,
    `strategy_name` LowCardinality(String),
    `from_version` Nullable(String),
    `to_version` String,
    `runtime_type` LowCardinality(String) DEFAULT 'JAR',
    `event_type` LowCardinality(String),
    `reason` String,
    `source` LowCardinality(String),
    `payload` String
)
ENGINE = MergeTree
ORDER BY (event_time, strategy_name, to_version)
SETTINGS index_granularity = 8192;
