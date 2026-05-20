CREATE TABLE IF NOT EXISTS dc.symbol_meta
(
    `symbol` String COMMENT '交易对代码，例如 ETHUSDT',
    `enabled` UInt8 DEFAULT 1 COMMENT '是否启用：1 启用，0 停用',
    `strategy_group` String DEFAULT '' COMMENT '策略分组，例如 range/trend/all',
    `scene` String DEFAULT '' COMMENT '适用场景，可选，例如 oscillation/trend/channel',
    `remark` String DEFAULT '' COMMENT '备注',
    `source` String DEFAULT 'manual' COMMENT '来源标记，例如 manual/db',
    `updated_time` DateTime DEFAULT now() COMMENT '最后更新时间'
)
ENGINE = ReplacingMergeTree(updated_time)
ORDER BY symbol
SETTINGS index_granularity = 8192
COMMENT '运行交易品种配置表';
