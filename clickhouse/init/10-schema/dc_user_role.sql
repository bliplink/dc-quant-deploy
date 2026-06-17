CREATE TABLE IF NOT EXISTS dc.dc_user_role
(
    `user_id` String,
    `role_id` String,
    `user_name` Nullable(String),
    `role_name` Nullable(String),
    `close_by` Nullable(String),
    `create_time` Nullable(String),
    `update_time` Nullable(String),
    `inf1` Nullable(String),
    `inf2` Nullable(String),
    `inf3` Nullable(String),
    `inf4` Nullable(String),
    `inf5` Nullable(String)
)
ENGINE = ReplacingMergeTree
ORDER BY (user_id, role_id)
SETTINGS index_granularity = 8192;
