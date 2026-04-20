CREATE TABLE IF NOT EXISTS dc.strategy_source_norm
(
    `id` String,
    `raw_id` String,
    `source_type` String,
    `site_name` String,
    `canonical_url` String,
    `normalized_title` String,
    `scene` String,
    `strategy_name` String,
    `description` String,
    `content` String,
    `raw_content_hash` String,
    `fingerprint` String,
    `status` String,
    `create_time` DateTime,
    `update_time` Nullable(DateTime),
    `payload` String
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(create_time)
ORDER BY (scene, strategy_name, fingerprint, id, create_time)
SETTINGS index_granularity = 8192;
