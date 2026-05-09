CREATE TABLE IF NOT EXISTS dc.deepseek_market_scene_analysis
(
    `id` String,
    `symbol` String,
    `run_time` DateTime,
    `analysis_type` String,
    `prompt_version` String,
    `latest_stage` String,
    `d1_background` String,
    `h1_structure` String,
    `m15_confirmation` String,
    `scene` String,
    `strategy` String,
    `strategy_type` String,
    `risk_level` String,
    `confidence` Nullable(Float64),
    `reason` String,
    `warnings_json` String,
    `data_quality_json` String,
    `feature_json` String,
    `recent_klines_json` String,
    `prompt_text` String,
    `response_json` String,
    `validator_result_json` String,
    `llm_call_log_id` String,
    `status` String,
    `error_message` String,
    `created_at` DateTime
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(run_time)
ORDER BY (symbol, run_time, id)
SETTINGS index_granularity = 8192
COMMENT 'DeepSeek market scene analysis facts';
