CREATE TABLE IF NOT EXISTS dc.strategy_quality_event
(
    `id` String,
    `event_type` LowCardinality(String),
    `source_stage` LowCardinality(String),
    `reason_code` LowCardinality(String),
    `reason_text` String,
    `severity` UInt8 DEFAULT 50,
    `symbol` String DEFAULT '',
    `scene` LowCardinality(String) DEFAULT '',
    `strategy_name` String DEFAULT '',
    `strategy_version` String DEFAULT '',
    `runtime_type` LowCardinality(String) DEFAULT 'JAR',
    `archetype` String DEFAULT '',
    `source_table` String DEFAULT '',
    `source_id` String DEFAULT '',
    `generation_task_id` String DEFAULT '',
    `backtest_task_id` String DEFAULT '',
    `candidate_id` String DEFAULT '',
    `score_impact` Float64 DEFAULT 0,
    `evidence_json` String DEFAULT '',
    `event_time` DateTime,
    `ingest_time` DateTime
)
ENGINE = ReplacingMergeTree(ingest_time)
PARTITION BY toYYYYMM(event_time)
ORDER BY (symbol, scene, event_time, id)
TTL event_time + toIntervalDay(365)
SETTINGS index_granularity = 8192;
