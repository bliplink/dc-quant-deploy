-- dc.kline_view source

CREATE VIEW IF NOT EXISTS dc.kline_view
(

    `startTime` DateTime64(6),

    `endTime` DateTime64(6),

    `securityID` String,

    `text` String,

    `fmtTime` String,
	`inf1` String,

    `open` Decimal(76,
 9),

    `close` Decimal(76,
 9),

    `low` Decimal(76,
 9),

    `high` Decimal(76,
 9),

    `turnover` Decimal(76,
 2),

    `volume` Decimal(76,
 2)
)
AS SELECT
    startTime,

    argMax(endTime,
 createTime) AS endTime,

    securityID,

    text,

    fmtTime,

    argMax(open,
 createTime) AS open,

    argMax(close,
 createTime) AS close,

    argMax(low,
 createTime) AS low,

    argMax(high,
 createTime) AS high,

    argMax(turnover,
 createTime) AS turnover,

    argMax(volume,
 createTime) AS volume,
     argMax(inf1,
 createTime) AS inf1
FROM dc.kline
GROUP BY
    startTime,

    fmtTime,

    securityID,

    text;