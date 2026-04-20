-- dc.kline definition

CREATE TABLE IF NOT EXISTS dc.kline
(

    `startTime` DateTime64(6) CODEC(LZ4),

    `endTime` DateTime64(6) CODEC(LZ4),

    `securityID` String CODEC(LZ4),

    `text` String CODEC(LZ4),

    `fmtTime` String CODEC(LZ4),

    `open` Nullable(Decimal(76,
 9)) CODEC(LZ4),

    `high` Nullable(Decimal(76,
 9)) CODEC(LZ4),

    `low` Nullable(Decimal(76,
 9)) CODEC(LZ4),

    `close` Nullable(Decimal(76,
 9)) CODEC(LZ4),

    `openTime` Nullable(DateTime64(6)) CODEC(LZ4),

    `highTime` Nullable(DateTime64(6)) CODEC(LZ4),

    `lowTime` Nullable(DateTime64(6)) CODEC(LZ4),

    `closeTime` Nullable(DateTime64(6)) CODEC(LZ4),

    `inf1` Nullable(String) CODEC(LZ4),

    `inf2` Nullable(String) CODEC(LZ4),

    `inf3` Nullable(String) CODEC(LZ4),

    `inf4` Nullable(String) CODEC(LZ4),

    `type` String CODEC(LZ4),

    `venue` String CODEC(LZ4),

    `createTime` DateTime64(6) CODEC(LZ4),

    `fillFlag` Nullable(Int8) CODEC(LZ4),

    `numTrades` Int32 CODEC(LZ4),

    `openInterest` Nullable(Decimal(76,
 9)) CODEC(LZ4),

    `preSettlePrice` Nullable(Decimal(76,
 9)) CODEC(LZ4),

    `turnover` Decimal(76,
 2) CODEC(LZ4),

    `volume` Decimal(76,
 2) CODEC(LZ4)
)
ENGINE = ReplacingMergeTree(createTime)
PARTITION BY toYYYYMM(startTime)
PRIMARY KEY (startTime,
 securityID,
 text,
 fmtTime)
ORDER BY (startTime,
 securityID,
 text,
 fmtTime)
SETTINGS index_granularity = 8192;