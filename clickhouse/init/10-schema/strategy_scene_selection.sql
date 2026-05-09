CREATE TABLE IF NOT EXISTS dc.strategy_scene_selection
(
    `selection_time` DateTime COMMENT 'selection time',
    `scene` String COMMENT 'scene code: range/trend/channel',
    `symbol` String COMMENT 'symbol such as BTCUSDT',
    `strategy_name` String COMMENT 'selected live strategy name',
    `payload` String COMMENT 'selection audit payload json'
)
ENGINE = MergeTree
PARTITION BY toDate(selection_time)
ORDER BY (symbol, selection_time)
SETTINGS index_granularity = 8192
COMMENT 'scene strategy selection records';
