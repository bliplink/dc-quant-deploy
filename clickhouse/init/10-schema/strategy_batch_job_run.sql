CREATE TABLE IF NOT EXISTS dc.strategy_batch_job_run
(
    `id` String,
    `job_name` LowCardinality(String),
    `action` LowCardinality(String),
    `trigger_source` LowCardinality(String),
    `report_date` String DEFAULT '',
    `data_window` String DEFAULT '',
    `status` LowCardinality(String),
    `result_ref` String DEFAULT '',
    `result_json` String DEFAULT '',
    `payload` String DEFAULT '',
    `failure_reason` String DEFAULT '',
    `create_time` DateTime,
    `update_time` DateTime
)
ENGINE = ReplacingMergeTree(update_time)
PARTITION BY toYYYYMM(update_time)
ORDER BY (job_name, action, report_date, id)
SETTINGS index_granularity = 8192;
