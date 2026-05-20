CREATE TABLE IF NOT EXISTS dc.quant_signal_block_event
(
    `id` String,
    `tradeDate` Date32,
    `createTime` String,
    `quantID` String,
    `userID` String,
    `algoName` String,
    `venueTypeGW` String,
    `securityID` String,
    `symbol` String,
    `text` String,
    `signalID` String,
    `side` String,
    `ocType` String,
    `type` String,
    `price` Nullable(Decimal(38, 12)),
    `stopPrice` Nullable(Decimal(38, 12)),
    `takerPrice` Nullable(Decimal(38, 12)),
    `rejectStage` String,
    `rejectReason` String,
    `source` String,
    `scene` LowCardinality(String) DEFAULT '',
    `strategyName` LowCardinality(String) DEFAULT '',
    `strategyVersion` String DEFAULT '',
    `strategyPayload` String DEFAULT ''
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(tradeDate)
ORDER BY (tradeDate, quantID, venueTypeGW, securityID, createTime, signalID)
SETTINGS index_granularity = 8192;
