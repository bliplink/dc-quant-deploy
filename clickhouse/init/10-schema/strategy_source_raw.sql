CREATE TABLE IF NOT EXISTS dc.strategy_source_raw
(
    `id` String,
    `source_type` String,
    `site_name` String,
    `source_name` String,
    `external_id` String,
    `canonical_url` String,
    `source_url` String,
    `title` String,
    `author` String,
    `published_time` Nullable(DateTime),
    `update_time` Nullable(DateTime),
    `content_hash` String,
    `content` String,
    `status` String,
    `create_time` DateTime,
    `payload` String
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(create_time)
ORDER BY (source_type, external_id, id, create_time)
SETTINGS index_granularity = 8192;
