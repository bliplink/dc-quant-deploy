CREATE TABLE IF NOT EXISTS dc.strategy_live_registry
(
    `id` String,
    `strategy_name` LowCardinality(String),
    `strategy_version` String,
    `category` LowCardinality(String),
    `scene` LowCardinality(String),
    `runtime_type` LowCardinality(String) DEFAULT 'JAR',
    `symbol_scope` String,
    `text_scope` String,
    `artifact_uri` String,
    `entry_class` String,
    `parameters_json` String,
    `status` LowCardinality(String) DEFAULT 'ACTIVE',
    `effective_time` DateTime,
    `retire_time` Nullable(DateTime),
    `source` LowCardinality(String),
    `payload` String,
    `description` String DEFAULT ''
)
ENGINE = ReplacingMergeTree(effective_time)
ORDER BY (strategy_name, strategy_version, runtime_type, effective_time)
SETTINGS index_granularity = 8192;
