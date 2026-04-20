CREATE TABLE IF NOT EXISTS dc.quant_account_balance
(
    `id` String,
    `tradeDate` Date32,
    `eventTime` String,
    `createTime` String,
    `updateTime` UInt64,
    `source` String,
    `quantID` String,
    `userID` String,
    `accountID` String,
    `currency` String,
    `venueTypeGW` String,
    `venues` String,
    `securityID` String,
    `positionType` String,
    `accountStatus` String,
    `marketIndicator` String,
    `location` String,
    `demo` String,
    `isTrader` String,
    `balance` Nullable(Decimal(38, 12)),
    `usedMargin` Nullable(Decimal(38, 12)),
    `wdBalance` Nullable(Decimal(38, 12)),
    `dayRealizedPnl` Nullable(Decimal(38, 12)),
    `holdRealizedPnl` Nullable(Decimal(38, 12)),
    `dayCommission` Nullable(Decimal(38, 12)),
    `freezedMargin` Nullable(Decimal(38, 12)),
    `freezedCommission` Nullable(Decimal(38, 12)),
    `freezedBalance` Nullable(Decimal(38, 12)),
    `info1` String,
    `info2` String,
    `info3` String,
    `info4` String,
    `info5` String
)
ENGINE = ReplacingMergeTree(updateTime)
PARTITION BY cityHash64(location, quantID, venueTypeGW, marketIndicator, accountID, currency, positionType, securityID) % 16
ORDER BY (location, quantID, venueTypeGW, marketIndicator, accountID, currency, positionType, securityID)
SETTINGS index_granularity = 8192;
