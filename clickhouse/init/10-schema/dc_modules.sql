CREATE TABLE IF NOT EXISTS dc.dc_modules
(
    `id` String,
    `module_name` String,
    `parent_id` String,
    `terminal` Nullable(String),
    `ip` Nullable(String),
    `close_by` Nullable(String),
    `remark` Nullable(String),
    `create_time` Nullable(String),
    `update_time` Nullable(String),
    `inf1` Nullable(String),
    `inf2` Nullable(String),
    `inf3` Nullable(String),
    `inf4` Nullable(String),
    `inf5` Nullable(String)
)
ENGINE = ReplacingMergeTree
ORDER BY id
SETTINGS index_granularity = 8192;
