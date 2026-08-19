CREATE TABLE IF NOT EXISTS dc.cus_signal
(
    `id` String,
    `tradeDate` String,
    `algoName` String,
    `strategyName` String DEFAULT '',
    `strategyVersion` String DEFAULT '',
    `scene` String DEFAULT '',
    `strategyPayload` String DEFAULT '',
    `symbol` String,
    `text` String,
    `side` String,
    `ocType` String,
    `price` Decimal(28, 8),
    `stopPrice` Decimal(28, 8),
    `takerPrice` Decimal(28, 8),
    `type` Int32,
    `remark` String,
    `venueTypeGW` String,
    `createTime` String
)
ENGINE = MergeTree
ORDER BY (symbol, text, createTime, id)
SETTINGS index_granularity = 8192;

ALTER TABLE dc.cus_signal ADD COLUMN IF NOT EXISTS strategyName String DEFAULT '' AFTER algoName;
ALTER TABLE dc.cus_signal ADD COLUMN IF NOT EXISTS strategyVersion String DEFAULT '' AFTER strategyName;
ALTER TABLE dc.cus_signal ADD COLUMN IF NOT EXISTS scene String DEFAULT '' AFTER strategyVersion;
ALTER TABLE dc.cus_signal ADD COLUMN IF NOT EXISTS strategyPayload String DEFAULT '' AFTER scene;
