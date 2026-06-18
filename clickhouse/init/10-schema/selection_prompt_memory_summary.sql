CREATE TABLE IF NOT EXISTS dc.selection_prompt_memory_summary
(
    `id` String,
    `symbol` String DEFAULT '',
    `scene` LowCardinality(String) DEFAULT '',
    `time_range_days` UInt16 DEFAULT 30,
    `candidate_count_stats_json` String DEFAULT '',
    `selection_bias_json` String DEFAULT '',
    `underperform_reason_topn_json` String DEFAULT '',
    `better_candidate_patterns_json` String DEFAULT '',
    `summary_text` String DEFAULT '',
    `update_time` DateTime
)
ENGINE = ReplacingMergeTree(update_time)
ORDER BY (symbol, scene, time_range_days, id)
SETTINGS index_granularity = 8192;
