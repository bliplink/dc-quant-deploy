CREATE TABLE IF NOT EXISTS dc.strategy_prompt_memory_summary
(
    `id` String,
    `summary_type` LowCardinality(String) DEFAULT 'SYMBOL_SCENE',
    `symbol` String DEFAULT '',
    `scene` LowCardinality(String) DEFAULT '',
    `archetype` String DEFAULT '',
    `time_range_days` UInt16 DEFAULT 30,
    `event_count` UInt32 DEFAULT 0,
    `success_count` UInt32 DEFAULT 0,
    `failure_count` UInt32 DEFAULT 0,
    `near_pass_count` UInt32 DEFAULT 0,
    `top_failure_codes_json` String DEFAULT '',
    `top_success_patterns_json` String DEFAULT '',
    `near_pass_patterns_json` String DEFAULT '',
    `summary_text` String DEFAULT '',
    `update_time` DateTime
)
ENGINE = ReplacingMergeTree(update_time)
ORDER BY (summary_type, symbol, scene, archetype, time_range_days, id)
SETTINGS index_granularity = 8192;
