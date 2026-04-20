CREATE TABLE IF NOT EXISTS dc.strategy_pipeline_run
(
    `run_id` String,
    `source_type` String CODEC(LZ4),
    `source_ref` String CODEC(LZ4),
    `strategy_name` String CODEC(LZ4),
    `strategy_version` String CODEC(LZ4),
    `current_stage` String CODEC(LZ4),
    `current_status` String CODEC(LZ4),
    `current_reason` String CODEC(LZ4),
    `payload` String CODEC(LZ4),
    `create_time` DateTime CODEC(LZ4),
    `update_time` DateTime CODEC(LZ4)
)
ENGINE = ReplacingMergeTree(update_time)
PARTITION BY toYYYYMM(update_time)
ORDER BY (run_id, update_time)
SETTINGS index_granularity = 8192;
