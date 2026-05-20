CREATE TABLE IF NOT EXISTS dc.strategy_source_raw
(
    `id` String,
    `source_name` LowCardinality(String),
    `source_url` String,
    `source_type` LowCardinality(String),
    `title` String,
    `category_raw` String,
    `logic_raw` String,
    `market_raw` String,
    `symbol_scope_raw` String,
    `crawl_time` DateTime,
    `source_hash` String,
    `payload` String,
    `status` LowCardinality(String) DEFAULT 'NEW',
    `site_name` String DEFAULT '',
    `external_id` String DEFAULT '',
    `canonical_url` String DEFAULT '',
    `author` String DEFAULT '',
    `published_time` Nullable(DateTime),
    `content_hash` String DEFAULT '',
    `update_time` Nullable(DateTime),
    `content` String DEFAULT '',
    `create_time` DateTime DEFAULT crawl_time
)
ENGINE = ReplacingMergeTree(crawl_time)
ORDER BY (source_name, source_hash, crawl_time)
SETTINGS index_granularity = 8192;
