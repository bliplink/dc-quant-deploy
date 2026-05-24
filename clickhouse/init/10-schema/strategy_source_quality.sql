CREATE TABLE IF NOT EXISTS dc.strategy_source_quality
(
    `id` String,
    `norm_id` String,
    `raw_id` String,
    `source_type` String,
    `site_name` String,
    `canonical_url` String,
    `normalized_title` String,
    `original_title` String,
    `scene` String,
    `strategy_title` String,
    `strategy_description` String,
    `recommended_text` String,
    `recommended_symbol` String,
    `quality_score` Nullable(Float64),
    `risk_level` String,
    `prefilter_score` Nullable(Int32),
    `prefilter_reason` String,
    `dedupe_status` String,
    `dedupe_reason` String,
    `master_quality_id` String,
    `provider` String,
    `model` String,
    `prompt_version` String,
    `llm_call_log_id` String,
    `prompt_text` String,
    `response_text` String,
    `total_tokens` Nullable(Int32),
    `duration_ms` Nullable(Int64),
    `status` String,
    `submit_status` String,
    `generation_task_id` String,
    `backtest_task_id` String,
    `payload` String,
    `fingerprint` String,
    `content` String,
    `create_time` DateTime,
    `update_time` DateTime
)
ENGINE = ReplacingMergeTree(update_time)
PARTITION BY toYYYYMM(update_time)
ORDER BY (norm_id, id)
SETTINGS index_granularity = 8192;
