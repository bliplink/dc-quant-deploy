CREATE TABLE IF NOT EXISTS dc.strategy_candidate
(
    `id` String,
    `strategy_name` LowCardinality(String),
    `strategy_version` String,
    `parent_version` Nullable(String),
    `category` LowCardinality(String),
    `scene` LowCardinality(String),
    `runtime_type` LowCardinality(String) DEFAULT 'JAR',
    `source_ref` String,
    `generation_type` LowCardinality(String),
    `logic_summary` String,
    `java_source_path` String,
    `artifact_uri` String,
    `entry_class` String,
    `checksum` String,
    `description` String DEFAULT '',
    `parameters_json` String DEFAULT '',
    `compile_status` LowCardinality(String) DEFAULT 'COMPILE_PENDING',
    `status` LowCardinality(String) DEFAULT 'SOURCE_GENERATED',
    `create_time` DateTime,
    `payload` String
)
ENGINE = ReplacingMergeTree(create_time)
ORDER BY (strategy_name, strategy_version, create_time)
SETTINGS index_granularity = 8192;
