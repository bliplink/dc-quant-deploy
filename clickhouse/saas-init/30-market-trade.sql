-- Existing MD CommonDataManager inserts MarketTrade rows into market_trade.
-- This missing Demo ClickHouse table caused repeated BatchClickHouseTask
-- UNKNOWN_TABLE failures. This does not change the tenant product schema.
CREATE TABLE IF NOT EXISTS dc.market_trade
(
    location String CODEC(LZ4),
    transactTime String CODEC(LZ4),
    securityID String CODEC(LZ4),
    marketIndicator String CODEC(LZ4),
    execID String CODEC(LZ4),
    price Decimal(38,18) CODEC(LZ4),
    quantity Decimal(38,18) CODEC(LZ4),
    amount Decimal(38,18) CODEC(LZ4),
    createTime String CODEC(LZ4),
    ingestionTime DateTime DEFAULT now() CODEC(LZ4)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(ingestionTime)
ORDER BY (location,securityID,marketIndicator,ingestionTime,execID)
TTL ingestionTime + INTERVAL 2 DAY DELETE
SETTINGS index_granularity = 8192;
