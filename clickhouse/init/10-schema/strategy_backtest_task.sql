CREATE TABLE IF NOT EXISTS dc.strategy_backtest_task
(
    `id` String,
    `candidate_id` String DEFAULT '',
    `generation_task_id` String DEFAULT '',
    `strategy_name` LowCardinality(String),
    `strategy_version` String,
    `baseline_version` Nullable(String),
    `runtime_type` LowCardinality(String) DEFAULT 'JAR',
    `task_type` LowCardinality(String),
    `fit_window_days` UInt16 DEFAULT 120,
    `validate_window_days` UInt16 DEFAULT 30,
    `forward_window_days` UInt16 DEFAULT 14,
    `priority` UInt8 DEFAULT 5,
    `status` LowCardinality(String) DEFAULT 'PENDING',
    `create_time` DateTime,
    `update_time` DateTime,
    `payload` String,
    `failure_reason` String DEFAULT '',
    `published_live` UInt8 DEFAULT 0,
    `suspend_reason` String DEFAULT '',
    `next_retry_time` Nullable(DateTime),
    `attempt_count` UInt16 DEFAULT 0
)
ENGINE = ReplacingMergeTree(update_time)
ORDER BY (status, priority, create_time, strategy_name, strategy_version)
SETTINGS index_granularity = 8192;
