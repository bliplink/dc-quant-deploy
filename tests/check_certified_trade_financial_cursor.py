#!/usr/bin/env python3
"""Compare Trade SQL balances and positions with certified mutations at one cursor snapshot."""
import argparse
import json
import re
import subprocess


BALANCE = ("balance", "usedMargin", "freezedMargin", "freezedCommission")
POSITION = ("leverage", "longPosition", "longAverage", "longUsedMargin", "shortPosition",
            "shortAverage", "shortUsedMargin", "longLockedPosition", "shortLockedPosition",
            "longLiqPrice", "shortLiqPrice")


def mismatches(alias, fields, precision):
    terms = []
    for field in fields:
        column = re.sub(r"[A-Z]", lambda match: "_" + match[0].lower(), field)
        value = f"JSON_UNQUOTE(JSON_EXTRACT(m.payload,'$.{field}'))"
        terms.append(f"({value} IS NULL OR {value}='null' OR "
                     f"NOT({alias}.{column} <=> CAST({value} AS DECIMAL({precision}))))")
    return " OR ".join(terms)


def statement(min_epoch, predecessors=False):
    predecessor_query = """
WITH history AS (
 SELECT source_epoch,journal_seq,previous_epoch,previous_seq,
   LAG(source_epoch,1,0) OVER (PARTITION BY partition_id ORDER BY source_epoch,journal_seq) AS actual_epoch,
   LAG(journal_seq,1,0) OVER (PARTITION BY partition_id ORDER BY source_epoch,journal_seq) AS actual_seq
 FROM dc_trade_projection_event
)
SELECT 'predecessor_links',COUNT(*),COUNT(CASE WHEN NOT(
       (previous_epoch <=> actual_epoch) AND (previous_seq <=> actual_seq)
       OR previous_epoch IS NULL AND previous_seq IS NULL AND source_epoch=2
          AND (actual_epoch=2 OR actual_epoch=0 AND actual_seq=0))
    THEN 1 END) FROM history;
""" if predecessors else ""
    return f"""
SET TRANSACTION ISOLATION LEVEL REPEATABLE READ;
START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY;
SELECT 'watermarks', COUNT(*),
  COUNT(CASE WHEN c.partition_id IS NULL OR w.source_epoch<>c.source_epoch
       OR w.journal_seq<>c.journal_seq THEN 1 END),
  COUNT(CASE WHEN w.source_epoch>={min_epoch} AND w.journal_seq>0 THEN 1 END)
 FROM dc_trade_projection_watermark w LEFT JOIN dc_trade_financial_readmodel_cursor c USING (partition_id);
SELECT 'extra_cursors',COUNT(*) FROM dc_trade_financial_readmodel_cursor c
 LEFT JOIN dc_trade_projection_watermark w USING (partition_id) WHERE w.partition_id IS NULL;
WITH ranges AS (
 SELECT partition_id,source_epoch,MIN(journal_seq) AS first_seq,MAX(journal_seq) AS last_seq,
        COUNT(*) AS frames FROM dc_trade_projection_event GROUP BY partition_id,source_epoch
)
SELECT 'source_epoch_ranges', COUNT(*), COUNT(CASE WHEN w.partition_id IS NULL
    OR r.source_epoch<2 OR r.first_seq<>1 OR r.last_seq<>r.frames
    OR r.source_epoch>w.source_epoch OR (r.source_epoch=w.source_epoch AND r.last_seq<>w.journal_seq)
    THEN 1 END), COUNT(CASE WHEN r.source_epoch<w.source_epoch THEN 1 END)
 FROM ranges r LEFT JOIN dc_trade_projection_watermark w USING (partition_id);
SELECT 'missing_source_heads',COUNT(*) FROM dc_trade_projection_watermark w
 LEFT JOIN dc_trade_projection_event e ON e.partition_id=w.partition_id
 AND e.source_epoch=w.source_epoch AND e.journal_seq=w.journal_seq
 WHERE w.journal_seq>0 AND e.partition_id IS NULL;
{predecessor_query}
WITH latest AS (
 SELECT m.entity_type,m.entity_key,m.location,m.operation,m.payload,m.source_epoch,
   ROW_NUMBER() OVER (PARTITION BY m.entity_type,m.entity_key
       ORDER BY m.source_epoch DESC,m.journal_seq DESC,m.mutation_index DESC) AS rank_at_cursor
 FROM dc_trade_projection_mutation m
 JOIN dc_trade_financial_readmodel_cursor c ON c.partition_id=m.partition_id
 WHERE (m.source_epoch<c.source_epoch OR (m.source_epoch=c.source_epoch AND m.journal_seq<=c.journal_seq))
 AND m.entity_type IN ('ACCOUNT_BALANCE','POSITION')
)
SELECT m.entity_type,COUNT(*),
  SUM(CASE
      WHEN m.operation NOT IN ('UPSERT','REMOVE') THEN 1
      WHEN m.entity_type='ACCOUNT_BALANCE' AND m.operation='UPSERT' AND
           (b.user_id IS NULL OR {mismatches('b', BALANCE, '30,16')}) THEN 1
      WHEN m.entity_type='POSITION' AND m.operation='UPSERT' AND (p.user_id IS NULL OR
           NOT(p.position_type <=> JSON_UNQUOTE(JSON_EXTRACT(m.payload,'$.positionType'))) OR
           {mismatches('p', POSITION, '35,9')}) THEN 1
      WHEN m.operation='REMOVE' AND (b.user_id IS NOT NULL OR p.user_id IS NOT NULL) THEN 1
      ELSE 0 END),COUNT(CASE WHEN m.source_epoch>={min_epoch} THEN 1 END)
 FROM latest m
 LEFT JOIN dc_users_balance b ON m.entity_type='ACCOUNT_BALANCE' AND b.location=m.location
   AND b.user_id=SUBSTRING_INDEX(m.entity_key,CHAR(31),-1)
 LEFT JOIN dc_orders_position p ON m.entity_type='POSITION' AND p.location=m.location
   AND p.user_id=SUBSTRING_INDEX(SUBSTRING_INDEX(m.entity_key,CHAR(31),2),CHAR(31),-1)
   AND p.security_id=SUBSTRING_INDEX(m.entity_key,CHAR(31),-1)
 WHERE rank_at_cursor=1
 GROUP BY m.entity_type
 UNION ALL
 SELECT 'EXTRA_BALANCE',COUNT(*),COUNT(CASE WHEN NOT(b.balance <=> 0 AND b.used_margin <=> 0
    AND b.freezed_margin <=> 0 AND b.freezed_commission <=> 0) THEN 1 END),0
 FROM dc_users_balance b LEFT JOIN latest m ON m.rank_at_cursor=1 AND m.entity_type='ACCOUNT_BALANCE'
    AND b.location=m.location AND b.user_id=SUBSTRING_INDEX(m.entity_key,CHAR(31),-1)
 WHERE m.rank_at_cursor IS NULL
 UNION ALL
 SELECT 'EXTRA_POSITION',COUNT(*),COUNT(*),0
 FROM dc_orders_position p LEFT JOIN latest m ON m.rank_at_cursor=1 AND m.entity_type='POSITION'
    AND p.location=m.location AND p.user_id=SUBSTRING_INDEX(SUBSTRING_INDEX(m.entity_key,CHAR(31),2),CHAR(31),-1)
    AND p.security_id=SUBSTRING_INDEX(m.entity_key,CHAR(31),-1)
 WHERE m.rank_at_cursor IS NULL;
COMMIT;
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mysql", required=True)
    parser.add_argument("--min-epoch", type=int, default=2)
    parser.add_argument("--require-predecessors", action="store_true", help="Verify persisted prior coordinates across Epochs")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", args.mysql) or not 2 <= args.min_epoch <= 2**63-1:
        parser.error("expected an exact MySQL container and a positive certified Epoch")
    try:
        result = subprocess.run(["docker", "exec", "-i", args.mysql, "sh", "-c",
                                 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -N dc'],
                                input=statement(args.min_epoch, args.require_predecessors), text=True,
                                capture_output=True, check=True, timeout=120)
        stats = {}
        columns = {"watermarks": 3, "extra_cursors": 1, "source_epoch_ranges": 3,
                   "missing_source_heads": 1, "ACCOUNT_BALANCE": 3, "POSITION": 3,
                   "EXTRA_BALANCE": 3, "EXTRA_POSITION": 3}
        if args.require_predecessors:
            columns["predecessor_links"] = 2
        for line in result.stdout.splitlines():
            name, *values = line.split("\t")
            if name not in columns or name in stats or len(values) != columns[name]:
                raise ValueError("invalid cursor census")
            stats[name] = [int(value) for value in values]
        if not (columns.keys() - {"ACCOUNT_BALANCE", "POSITION"}) <= stats.keys():
            raise ValueError("incomplete cursor census")
    except (OSError, ValueError, subprocess.SubprocessError):
        print(json.dumps({"status": "NO_GO", "reasons": ["FINANCIAL_CURSOR_EVIDENCE_UNAVAILABLE"]}))
        return 2
    cursors, behind, in_epoch = stats["watermarks"]
    problems = []
    if not cursors or behind or stats["extra_cursors"][0]:
        problems.append("FINANCIAL_CURSOR_DIFFERS_FROM_SOURCE")
    if not stats["source_epoch_ranges"][0] or stats["source_epoch_ranges"][1] or stats["missing_source_heads"][0]:
        problems.append("SQL_SOURCE_EVENT_SEQUENCE_OR_HEAD_MISSING")
    if args.require_predecessors and (not stats["predecessor_links"][0] or stats["predecessor_links"][1]):
        problems.append("SQL_SOURCE_PREDECESSOR_LINKS_DO_NOT_MATCH")
    # Tenant creation can provision zero-valued balance rows before any Trade mutation.
    if stats["EXTRA_BALANCE"][1] or stats["EXTRA_POSITION"][1]:
        problems.append("FINANCIAL_ROWS_WITHOUT_CERTIFIED_SOURCE")
    if not in_epoch:
        problems.append("NO_COMMITTED_SOURCE_EVENTS_IN_REQUIRED_EPOCH")
    for kind in ("ACCOUNT_BALANCE", "POSITION"):
        count, mismatches_at_cursor, updated_in_epoch = stats.get(kind, (0, 0, 0))
        if not count or mismatches_at_cursor:
            problems.append(kind + "_DOES_NOT_MATCH_CERTIFIED_MUTATIONS")
        if not updated_in_epoch:
            problems.append(kind + "_HAS_NO_EVIDENCE_IN_REQUIRED_EPOCH")
    print(json.dumps({"status": "NO_GO" if problems else "PASS_FINANCIAL_CURSOR",
                      "min_epoch": args.min_epoch, **stats, "reasons": problems}, sort_keys=True))
    return 2 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
