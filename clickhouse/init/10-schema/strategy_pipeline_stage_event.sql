CREATE TABLE IF NOT EXISTS dc.strategy_pipeline_stage_event
(
    `id` String,
    `run_id` String CODEC(LZ4),
    `source_type` String CODEC(LZ4),
    `source_ref` String CODEC(LZ4),
    `strategy_name` String CODEC(LZ4),
    `strategy_version` String CODEC(LZ4),
    `stage` String CODEC(LZ4),
    `status` String CODEC(LZ4),
    `reason` String CODEC(LZ4),
    `payload` String CODEC(LZ4),
    `start_time` Nullable(DateTime) CODEC(LZ4),
    `end_time` Nullable(DateTime) CODEC(LZ4),
    `elapsed_ms` Int64 CODEC(LZ4),
    `create_time` DateTime CODEC(LZ4)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(create_time)
ORDER BY (run_id, stage, create_time, id)
SETTINGS index_granularity = 8192;
