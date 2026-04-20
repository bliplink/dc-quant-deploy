CREATE TABLE IF NOT EXISTS dc.strategy_release_event
(
    `id` String,
    `event_time` DateTime CODEC(LZ4),
    `strategy_name` String CODEC(LZ4),
    `from_version` Nullable(String) CODEC(LZ4),
    `to_version` String CODEC(LZ4),
    `runtime_type` String CODEC(LZ4),
    `event_type` String CODEC(LZ4),
    `reason` String CODEC(LZ4),
    `source` String CODEC(LZ4),
    `payload` String CODEC(LZ4)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(event_time)
ORDER BY (strategy_name, event_time, event_type, to_version)
SETTINGS index_granularity = 8192;
