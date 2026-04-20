CREATE TABLE IF NOT EXISTS dc.strategy_candidate
(
    `id` String,
    `strategy_name` String,
    `strategy_version` String,
    `parent_version` Nullable(String),
    `category` String,
    `scene` String,
    `runtime_type` String DEFAULT 'JAR',
    `source_ref` String,
    `generation_type` String,
    `logic_summary` String,
    `java_source_path` String,
    `artifact_uri` String,
    `entry_class` String,
    `checksum` String,
    `description` String,
    `parameters_json` String,
    `compile_status` String DEFAULT 'COMPILE_PENDING',
    `status` String DEFAULT 'SOURCE_GENERATED',
    `create_time` DateTime,
    `payload` String
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(create_time)
ORDER BY (strategy_name, strategy_version, create_time)
SETTINGS index_granularity = 8192;

ALTER TABLE dc.strategy_candidate
    ADD COLUMN IF NOT EXISTS `description` String DEFAULT '' AFTER `checksum`;

ALTER TABLE dc.strategy_candidate
    ADD COLUMN IF NOT EXISTS `parameters_json` String DEFAULT '' AFTER `description`;
