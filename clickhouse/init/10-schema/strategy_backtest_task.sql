CREATE TABLE IF NOT EXISTS dc.strategy_backtest_task
(
    `id` String,
    `strategy_name` String,
    `strategy_version` String,
    `baseline_version` Nullable(String),
    `runtime_type` String DEFAULT 'JAR',
    `task_type` String,
    `fit_window_days` UInt16 DEFAULT 120,
    `validate_window_days` UInt16 DEFAULT 30,
    `forward_window_days` UInt16 DEFAULT 14,
    `priority` UInt8 DEFAULT 5,
    `status` String DEFAULT 'PENDING',
    `suspend_reason` String DEFAULT '',
    `next_retry_time` Nullable(DateTime),
    `attempt_count` UInt16 DEFAULT 0,
    `create_time` DateTime,
    `update_time` DateTime,
    `payload` String
)
ENGINE = ReplacingMergeTree(update_time)
PARTITION BY toYYYYMM(create_time)
ORDER BY (strategy_name, strategy_version, id, update_time)
SETTINGS index_granularity = 8192;
