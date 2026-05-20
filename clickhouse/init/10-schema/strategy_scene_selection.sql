CREATE TABLE IF NOT EXISTS dc.strategy_scene_selection
(
    `selection_time` DateTime COMMENT '选择时间',
    `scene` String COMMENT '场景类型（oscillation/trend/channel）',
    `symbol` String COMMENT '交易对代码，例如 ETHUSDT',
    `strategy_name` String COMMENT '已选策略名称（通常对应策略 Bean 名称）',
    `payload` String COMMENT '扩展负载（JSON 字符串，便于排查与回放）'
)
ENGINE = MergeTree
PARTITION BY toDate(selection_time)
ORDER BY (symbol, selection_time)
SETTINGS index_granularity = 8192
COMMENT '场景策略选择记录表';
