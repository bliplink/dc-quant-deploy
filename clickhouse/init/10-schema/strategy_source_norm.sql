CREATE TABLE IF NOT EXISTS dc.strategy_source_norm
(
    `id` String,
    `raw_id` String,
    `normalized_strategy_name` LowCardinality(String),
    `category` LowCardinality(String),
    `scene` LowCardinality(String),
    `logic_summary` String,
    `logic_structured_json` String,
    `market_scope` String,
    `symbol_scope` String,
    `dedup_key` String,
    `llm_model` String,
    `normalize_time` DateTime,
    `payload` String,
    `status` LowCardinality(String) DEFAULT 'READY',
    `content` String DEFAULT '',
    `strategy_name` String DEFAULT '',
    `description` String DEFAULT '',
    `create_time` DateTime DEFAULT now(),
    `normalized_title` String DEFAULT '',
    `source_type` String DEFAULT '',
    `canonical_url` String DEFAULT '',
    `site_name` String DEFAULT '',
    `fingerprint` String DEFAULT '',
    `update_time` Nullable(DateTime),
    `raw_content_hash` String DEFAULT ''
)
ENGINE = ReplacingMergeTree(normalize_time)
ORDER BY (category, normalized_strategy_name, dedup_key, normalize_time)
SETTINGS index_granularity = 8192;
