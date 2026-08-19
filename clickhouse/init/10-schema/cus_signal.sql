CREATE TABLE IF NOT EXISTS dc.cus_signal
(
    `id` String,
    `tradeDate` String,
    `algoName` String,
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
