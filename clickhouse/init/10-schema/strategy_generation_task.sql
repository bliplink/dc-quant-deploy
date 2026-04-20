CREATE TABLE IF NOT EXISTS dc.strategy_generation_task
(
    `id` String,
    `source_type` String,
    `provider` String,
    `strategy_name` String,
    `strategy_version` String,
    `parent_version` Nullable(String),
    `scene` String,
    `source_ref` String,
    `prompt_summary` String,
    `compile_status` String,
    `status` String,
    `artifact_uri` String,
    `entry_class` String,
    `create_time` DateTime,
    `update_time` DateTime,
    `payload` String,
    `compile_log` String
)
ENGINE = ReplacingMergeTree(update_time)
PARTITION BY toYYYYMM(create_time)
ORDER BY (strategy_name, strategy_version, id, update_time)
SETTINGS index_granularity = 8192;
