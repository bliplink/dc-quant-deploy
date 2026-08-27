CREATE VIEW IF NOT EXISTS dc.kline_view AS
SELECT
    location,
    startTime,
    endTime,
    securityID,
    text,
    fmtTime,
    inf1,
    open,
    close,
    low,
    high,
    turnover,
    volume,
    latestCreateTime AS createTime
FROM
(
    SELECT
        location,
        startTime,
        argMax(endTime, createTime) AS endTime,
        securityID,
        upperUTF8(text) AS text,
        fmtTime,
        argMax(inf1, createTime) AS inf1,
        argMax(open, createTime) AS open,
        argMax(close, createTime) AS close,
        argMax(low, createTime) AS low,
        argMax(high, createTime) AS high,
        argMax(turnover, createTime) AS turnover,
        argMax(volume, createTime) AS volume,
        max(createTime) AS latestCreateTime
    FROM dc.kline
    GROUP BY
        location,
        startTime,
        securityID,
        upperUTF8(text),
        fmtTime
);
