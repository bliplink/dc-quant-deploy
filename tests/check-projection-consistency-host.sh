#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${DEPLOY_DIR}/.env.prod}"
MYSQL_CONTAINER="${MYSQL_CONTAINER:-dc-saas-mysql}"
# Deep scans of multi-million-row mutation/event tables must fail closed before
# consuming the small Demo MySQL memory budget. Raise only during maintenance.
AUDIT_QUERY_MAX_MS="${PROJECTION_AUDIT_QUERY_MAX_MS:-15000}"
[[ "${AUDIT_QUERY_MAX_MS}" =~ ^[1-9][0-9]{3,5}$ ]] &&
  (( AUDIT_QUERY_MAX_MS <= 120000 )) || {
    printf '[projection-check] ERROR: invalid PROJECTION_AUDIT_QUERY_MAX_MS\\n' >&2
    exit 2
  }


log() { printf '[projection-check] %s\n' "$*"; }
die() { printf '[projection-check] ERROR: %s\n' "$*" >&2; exit 1; }

[[ -r "${ENV_FILE}" ]] || die "Cannot read ${ENV_FILE}"
set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a

mysql_exec() {
  docker exec -e MYSQL_PWD="${MYSQL_PASSWORD}" "${MYSQL_CONTAINER}" \
    mysql -u"${MYSQL_USERNAME}" -N "$@"
}

event_pk="$(mysql_exec -e "SELECT GROUP_CONCAT(column_name ORDER BY seq_in_index SEPARATOR ',') FROM information_schema.statistics WHERE table_schema='dc' AND table_name='dc_trade_projection_event' AND index_name='PRIMARY';")"
mutation_pk="$(mysql_exec -e "SELECT GROUP_CONCAT(column_name ORDER BY seq_in_index SEPARATOR ',') FROM information_schema.statistics WHERE table_schema='dc' AND table_name='dc_trade_projection_mutation' AND index_name='PRIMARY';")"

[[ "${event_pk}" == "partition_id,source_epoch,journal_seq" ]] ||
  die "Unexpected dc_trade_projection_event primary key: ${event_pk}"
[[ "${mutation_pk}" == "partition_id,source_epoch,journal_seq,mutation_index" ]] ||
  die "Unexpected dc_trade_projection_mutation primary key: ${mutation_pk}"

orphan_mutations="$(mysql_exec -e "SELECT /*+ MAX_EXECUTION_TIME(${AUDIT_QUERY_MAX_MS}) */ COUNT(*) FROM dc.dc_trade_projection_mutation m LEFT JOIN dc.dc_trade_projection_event e ON e.partition_id=m.partition_id AND e.source_epoch=m.source_epoch AND e.journal_seq=m.journal_seq WHERE e.partition_id IS NULL;")"
[[ "${orphan_mutations}" == "0" ]] || die "Found ${orphan_mutations} orphan trade projection mutations"

# Use the partition/epoch/sequence primary key for bounded index-tail probes.
# GROUP BY over the full event journal can OOM the small Demo MySQL container.
watermark_mismatch="$(mysql_exec -e "
SELECT COUNT(*) FROM dc.dc_trade_projection_watermark w
WHERE NOT EXISTS (
    SELECT 1 FROM dc.dc_trade_projection_event e
    WHERE e.partition_id=w.partition_id AND e.source_epoch=w.source_epoch
      AND e.journal_seq=w.journal_seq)
   OR w.source_epoch <> (
    SELECT e.source_epoch FROM dc.dc_trade_projection_event e
    WHERE e.partition_id=w.partition_id
    ORDER BY e.partition_id DESC,e.source_epoch DESC,e.journal_seq DESC LIMIT 1)
   OR w.journal_seq <> (
    SELECT e.journal_seq FROM dc.dc_trade_projection_event e
    WHERE e.partition_id=w.partition_id
    ORDER BY e.partition_id DESC,e.source_epoch DESC,e.journal_seq DESC LIMIT 1);
")"
[[ "${watermark_mismatch}" == "0" ]] || die "Found ${watermark_mismatch} Trade Projection watermark/tail mismatches"

watermark_count="$(mysql_exec -e "SELECT COUNT(*) FROM dc.dc_trade_projection_watermark;")"
[[ "${watermark_count}" =~ ^[1-9][0-9]*$ ]] || die "Trade Projection has no durable watermarks"

# Event_id is the Order event PK; the partition/epoch/sequence UNIQUE index
# supplies the latest event without sorting/materializing the full journal.
order_event_sequence_index="$(mysql_exec -e "SELECT GROUP_CONCAT(column_name ORDER BY seq_in_index SEPARATOR ',') FROM information_schema.statistics WHERE table_schema='dc' AND table_name='dc_order_projection_event' AND index_name='uk_dc_order_projection_partition_seq';")"
[[ "${order_event_sequence_index}" == "partition_id,source_epoch,journal_seq" ]] ||
  die "Unexpected Order event sequence index: ${order_event_sequence_index}"
order_watermark_mismatch="$(mysql_exec -e "
SELECT COUNT(*) FROM dc.dc_order_projection_watermark w
WHERE NOT EXISTS (
    SELECT 1 FROM dc.dc_order_projection_event e
    WHERE e.partition_id=w.partition_id AND e.source_epoch=w.source_epoch
      AND e.journal_seq=w.journal_seq)
   OR w.source_epoch <> (
    SELECT e.source_epoch FROM dc.dc_order_projection_event e
      FORCE INDEX (uk_dc_order_projection_partition_seq)
    WHERE e.partition_id=w.partition_id
    ORDER BY e.partition_id DESC,e.source_epoch DESC,e.journal_seq DESC LIMIT 1)
   OR w.journal_seq <> (
    SELECT e.journal_seq FROM dc.dc_order_projection_event e
      FORCE INDEX (uk_dc_order_projection_partition_seq)
    WHERE e.partition_id=w.partition_id
    ORDER BY e.partition_id DESC,e.source_epoch DESC,e.journal_seq DESC LIMIT 1);
")"
[[ "${order_watermark_mismatch}" == "0" ]] || die "Found ${order_watermark_mismatch} Order Projection watermark/tail mismatches"

order_watermark_count="$(mysql_exec -e "SELECT COUNT(*) FROM dc.dc_order_projection_watermark;")"
[[ "${order_watermark_count}" =~ ^[1-9][0-9]*$ ]] || die "Order Projection has no durable watermarks"

cross_partition_event_ids="$(mysql_exec -e "SELECT /*+ MAX_EXECUTION_TIME(${AUDIT_QUERY_MAX_MS}) */ COUNT(*) FROM (SELECT event_id FROM dc.dc_trade_projection_event GROUP BY event_id HAVING COUNT(DISTINCT partition_id)>1) t;")"

log "PASS event_pk=${event_pk}"
log "PASS mutation_pk=${mutation_pk}"
log "PASS orphan_mutations=0"
log "PASS trade_watermark_tail_mismatch=0 watermarks=${watermark_count}"
log "PASS order_watermark_tail_mismatch=0 watermarks=${order_watermark_count}"
log "INFO cross_partition_event_ids=${cross_partition_event_ids}"
