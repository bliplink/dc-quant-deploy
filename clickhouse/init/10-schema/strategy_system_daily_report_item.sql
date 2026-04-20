CREATE TABLE IF NOT EXISTS dc.strategy_system_daily_report_item
(
    `id` String,
    `report_id` String CODEC(LZ4),
    `report_date` Date32 CODEC(LZ4),
    `section` String CODEC(LZ4),
    `item_key` String CODEC(LZ4),
    `item_name` String CODEC(LZ4),
    `metric_value` Float64 CODEC(LZ4),
    `metric_text` String CODEC(LZ4),
    `payload` String CODEC(LZ4),
    `create_time` DateTime CODEC(LZ4)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(report_date)
ORDER BY (report_date, report_id, section, item_key, id)
SETTINGS index_granularity = 8192;
