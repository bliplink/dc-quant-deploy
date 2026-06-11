CREATE TABLE IF NOT EXISTS dc.dc_audit_log
(
    `id` String,
    `user_id` Nullable(String),
    `type` Nullable(String),
    `status` Nullable(String),
    `ip` Nullable(String),
    `mac` Nullable(String),
    `terminal` Nullable(String),
    `content` Nullable(String),
    `create_time` Nullable(String),
    `close_by` Nullable(String)
)
ENGINE = MergeTree
ORDER BY (id, user_id)
SETTINGS index_granularity = 8192;
