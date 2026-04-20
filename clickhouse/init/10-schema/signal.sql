-- dc.signal definition

CREATE TABLE IF NOT EXISTS dc.signal
(

    `id` String CODEC(LZ4),

    `tradeDate` Date32 CODEC(LZ4),

    `algoName` String CODEC(LZ4),

    `strategyName` String CODEC(LZ4),

    `strategyVersion` String CODEC(LZ4),

    `scene` String CODEC(LZ4),

    `strategyPayload` String CODEC(LZ4),

    `symbol` String CODEC(LZ4),

    `text` String CODEC(LZ4),

    `side` Nullable(String) CODEC(LZ4),

    `ocType` Nullable(String) CODEC(LZ4),

    `price` Nullable(Decimal(18,
 4)) CODEC(LZ4),

    `stopPrice` Nullable(Decimal(18,
 4)) CODEC(LZ4),

    `takerPrice` Nullable(Decimal(18,
 4)) CODEC(LZ4),

    `type` Nullable(String) CODEC(LZ4),

    `remark` Nullable(String) CODEC(LZ4),

    `venueTypeGW` Nullable(String) CODEC(LZ4),

    `createTime` DateTime64(6) CODEC(LZ4)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(tradeDate)
ORDER BY (id,
 tradeDate,
 algoName,
 strategyName,
 symbol,
 text)
SETTINGS index_granularity = 8192;
