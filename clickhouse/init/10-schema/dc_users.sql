CREATE TABLE IF NOT EXISTS dc.dc_users
(
    `user_id` String,
    `user_name` String,
    `name` String,
    `password` Nullable(String),
    `mail` Nullable(String),
    `user_type` Nullable(String),
    `enable` Nullable(String),
    `remark` Nullable(String),
    `create_time` Nullable(String),
    `update_time` Nullable(String),
    `mac` Nullable(String),
    `mac1` Nullable(String),
    `mac2` Nullable(String),
    `inf1` Nullable(String),
    `inf2` Nullable(String),
    `inf3` Nullable(String),
    `inf4` Nullable(String),
    `inf5` Nullable(String),
    `enable_trade` Nullable(String),
    `enable_cash_in` Nullable(String),
    `enable_cash_out` Nullable(String),
    `referrer` Nullable(String),
    `close_by` Nullable(String),
    `location` Nullable(String)
)
ENGINE = ReplacingMergeTree
ORDER BY (user_name, user_id)
SETTINGS index_granularity = 8192;
