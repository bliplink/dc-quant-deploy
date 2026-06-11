CREATE TABLE IF NOT EXISTS dc.dc_users_session
(
    `token` String,
    `user_id` Nullable(String),
    `name` Nullable(String),
    `ip` Nullable(String),
    `create_time` Nullable(String),
    `client_type` Nullable(String),
    `infs` Nullable(String),
    `location` Nullable(String)
)
ENGINE = MergeTree
ORDER BY (token, user_id)
SETTINGS index_granularity = 8192;
