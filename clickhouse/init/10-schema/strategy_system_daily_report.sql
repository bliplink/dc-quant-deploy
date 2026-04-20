CREATE TABLE IF NOT EXISTS dc.strategy_system_daily_report
(
    `id` String,
    `report_date` Date32 CODEC(LZ4),
    `generated_at` DateTime CODEC(LZ4),
    `summary_json` String CODEC(LZ4),
    `html_path` String CODEC(LZ4),
    `json_path` String CODEC(LZ4),
    `payload` String CODEC(LZ4)
)
ENGINE = ReplacingMergeTree(generated_at)
PARTITION BY toYYYYMM(report_date)
ORDER BY (report_date, id, generated_at)
SETTINGS index_granularity = 8192;
