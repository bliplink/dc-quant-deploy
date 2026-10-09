-- MarketTrade is emitted by MDSvr CommonDataManager via ClickHouseDBUtils.insertList().
-- Keep an append-only log; failed batches prior to this migration are not backfilled.
-- Idempotent for both fresh SaaS bootstrap and existing persistent ClickHouse volumes.
CREATE TABLE IF NOT EXISTS dc.market_trade
(
    `location` String CODEC(LZ4),
    `transactTime` String CODEC(LZ4),
    `securityID` String CODEC(LZ4),
    `marketIndicator` String CODEC(LZ4),
    `execID` String CODEC(LZ4),
    `price` Decimal(76, 9) CODEC(LZ4),
    `quantity` Decimal(76, 9) CODEC(LZ4),
    `amount` Decimal(76, 9) CODEC(LZ4),
    `createTime` DateTime64(3) CODEC(LZ4)
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(createTime)
ORDER BY (location, securityID, createTime, execID)
TTL createTime + INTERVAL 30 DAY DELETE
SETTINGS index_granularity = 8192;
