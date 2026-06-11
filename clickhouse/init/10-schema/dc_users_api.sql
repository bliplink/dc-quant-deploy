CREATE TABLE IF NOT EXISTS dc.dc_users_api
(
    `user_id` String,
    `type` String,
    `api_key` String,
    `secret_key` Nullable(String),
    `enable` Nullable(String),
    `create_time` Nullable(String),
    `update_time` Nullable(String),
    `close_by` Nullable(String),
    `inf1` Nullable(String),
    `location` Nullable(String)
)
ENGINE = ReplacingMergeTree
ORDER BY (api_key, user_id, type)
SETTINGS index_granularity = 8192;
