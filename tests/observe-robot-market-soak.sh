#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${DEPLOY_DIR}/.env.prod}"
STATE_DIR="${ROBOT_SOAK_STATE_DIR:-/data/dc-saas-runtime/robot-soak}"
LOCATION="${ROBOT_SOAK_LOCATION:-WEB_E2E}"
ROBOT_ID="${ROBOT_SOAK_ROBOT_ID:-continuous-depth10}"
ROBOT_USER="${ROBOT_SOAK_ROBOT_USER:-robotsoakmaker}"
METRICS_FILE="${STATE_DIR}/depth-metrics.csv"
WEB_METRICS_FILE="${STATE_DIR}/web-metrics.csv"
WEB_HEARTBEAT_FILE="${STATE_DIR}/web-heartbeat.json"
SUMMARY_FILE="${STATE_DIR}/hourly-summary.csv"
SNAPSHOT_FILE="${STATE_DIR}/health-snapshot.json"
COUNTER_FILE="${STATE_DIR}/observer-counters"
LAST_SUMMARY_FILE="${STATE_DIR}/last-summary-hour"
LAST_ALERT_FILE="${STATE_DIR}/last-alert-signature"
ALERT_LOG="${STATE_DIR}/alerts.log"
LOCK_FILE="${STATE_DIR}/observer.lock"
MONITOR_CONTAINER="${ROBOT_SOAK_MONITOR_CONTAINER:-dc-saas-robot-web-monitor}"
WEB_STALE_SECONDS="${ROBOT_SOAK_MONITOR_STALE_SECONDS:-150}"
VISIBLE_DEPTH="${ROBOT_SOAK_VISIBLE_DEPTH:-10}"

log() { printf '[robot-observer] %s\n' "$*"; }
die() { printf '[robot-observer] ERROR: %s\n' "$*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || die "Run as root"
[[ -r "${ENV_FILE}" ]] || die "Cannot read ${ENV_FILE}"
[[ "${WEB_STALE_SECONDS}" =~ ^[1-9][0-9]*$ ]] || die "ROBOT_SOAK_MONITOR_STALE_SECONDS must be positive"
[[ "${VISIBLE_DEPTH}" =~ ^[1-9][0-9]*$ ]] || die "ROBOT_SOAK_VISIBLE_DEPTH must be positive"
mkdir -p "${STATE_DIR}"
touch "${ALERT_LOG}" "${LOCK_FILE}"
chmod 600 "${ALERT_LOG}"
exec 8>"${LOCK_FILE}"
flock -n 8 || exit 0

set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a

mysql_exec() {
  docker exec -e MYSQL_PWD="${MYSQL_PASSWORD}" dc-saas-mysql \
    mysql -u"${MYSQL_USERNAME}" -N "$@"
}

positive_delta() {
  local current="${1:-0}" previous="${2:-0}"
  if (( current >= previous )); then printf '%s' "$((current - previous))"; else printf '%s' "${current}"; fi
}

write_hourly_summary() {
  local hour last_hour active_stats web_stats status
  local active_samples min_bid max_bid min_ask max_ask http_bad accepted_delta rejected_delta gap_delta auth_delta
  local web_minutes web_min_bid web_max_bid web_min_ask web_max_ask web_gap_delta web_errors
  hour="$(date -u -d '1 hour ago' '+%Y-%m-%dT%H')"
  last_hour="$(cat "${LAST_SUMMARY_FILE}" 2>/dev/null || true)"
  [[ "${hour}" != "${last_hour}" ]] || return 0

  active_stats="$(awk -F, -v hour="${hour}" '
    NR == 1 {next}
    index($1,hour) == 1 {
      n++
      if (n == 1 || $2 < minBid) minBid=$2
      if (n == 1 || $2 > maxBid) maxBid=$2
      if (n == 1 || $3 < minAsk) minAsk=$3
      if (n == 1 || $3 > maxAsk) maxAsk=$3
      if ($5 != 200) httpBad++
      if (seen) {
        d=$6-prevAccepted; accepted += (d >= 0 ? d : $6)
        d=$7-prevRejected; rejected += (d >= 0 ? d : $7)
        d=$8-prevGap; gaps += (d >= 0 ? d : $8)
        d=$9-prevAuth; auth += (d >= 0 ? d : $9)
      }
      prevAccepted=$6; prevRejected=$7; prevGap=$8; prevAuth=$9; seen=1
    }
    END {printf "%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d", n,minBid,maxBid,minAsk,maxAsk,httpBad,accepted,rejected,gaps,auth}
  ' "${METRICS_FILE}" 2>/dev/null || printf '0\t0\t0\t0\t0\t0\t0\t0\t0\t0')"
  IFS=$'\t' read -r active_samples min_bid max_bid min_ask max_ask http_bad accepted_delta rejected_delta gap_delta auth_delta <<<"${active_stats}"

  web_stats="$(awk -F, -v hour="${hour}" '
    NR == 1 {next}
    index($1,hour) == 1 {
      n++
      if (n == 1 || $4 < minBid) minBid=$4
      if (n == 1 || $5 > maxBid) maxBid=$5
      if (n == 1 || $6 < minAsk) minAsk=$6
      if (n == 1 || $7 > maxAsk) maxAsk=$7
      errors += $8
      if (seen) {d=$3-prevGap; gaps += (d >= 0 ? d : $3)}
      prevGap=$3; seen=1
    }
    END {printf "%d\t%d\t%d\t%d\t%d\t%d\t%d", n,minBid,maxBid,minAsk,maxAsk,gaps,errors}
  ' "${WEB_METRICS_FILE}" 2>/dev/null || printf '0\t0\t0\t0\t0\t0\t0')"
  IFS=$'\t' read -r web_minutes web_min_bid web_max_bid web_min_ask web_max_ask web_gap_delta web_errors <<<"${web_stats}"

  status=PASS
  if (( active_samples == 0 && web_minutes == 0 )); then
    status=NO_DATA
  else
    if (( active_samples == 0 || min_bid < VISIBLE_DEPTH || min_ask < VISIBLE_DEPTH || http_bad > 0 || rejected_delta > 0 || gap_delta > 0 )); then status=FAIL; fi
    if (( web_minutes == 0 || web_min_bid != 10 || web_max_bid != 10 || web_min_ask != 10 || web_max_ask != 10 || web_gap_delta > 0 || web_errors > 0 )); then status=FAIL; fi
  fi
  if [[ ! -s "${SUMMARY_FILE}" ]]; then
    printf '%s\n' 'hour_utc,active_order_samples,min_bid,max_bid,min_ask,max_ask,http_bad,accepted,rejected,gaps,auth_refreshes,web_minutes,web_min_bid,web_max_bid,web_min_ask,web_max_ask,web_gaps,web_errors,status' >"${SUMMARY_FILE}"
  fi
  printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' \
    "${hour}:00Z" "${active_samples}" "${min_bid}" "${max_bid}" "${min_ask}" "${max_ask}" \
    "${http_bad}" "${accepted_delta}" "${rejected_delta}" "${gap_delta}" "${auth_delta}" \
    "${web_minutes}" "${web_min_bid}" "${web_max_bid}" "${web_min_ask}" "${web_max_ask}" \
    "${web_gap_delta}" "${web_errors}" "${status}" >>"${SUMMARY_FILE}"
  printf '%s\n' "${hour}" >"${LAST_SUMMARY_FILE}"
}

write_hourly_summary

issues=()
now_epoch="$(date +%s)"
timestamp="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
load_pid="$(cat "${STATE_DIR}/load.pid" 2>/dev/null || true)"
if [[ -z "${load_pid}" ]] || ! kill -0 "${load_pid}" 2>/dev/null; then issues+=("load_process_stopped"); fi

monitor_state="$(docker inspect --format '{{.State.Status}}' "${MONITOR_CONTAINER}" 2>/dev/null || echo missing)"
[[ "${monitor_state}" == "running" ]] || issues+=("web_monitor_${monitor_state}")
monitor_started_at="$(docker inspect --format '{{.State.StartedAt}}' "${MONITOR_CONTAINER}" 2>/dev/null || true)"
monitor_started_epoch="$(date -d "${monitor_started_at}" +%s 2>/dev/null || echo 0)"
monitor_age=$((now_epoch - monitor_started_epoch))

heartbeat_age=-1
web_state=missing
web_samples=0
web_gaps=0
web_min_bid=0
web_max_bid=0
web_min_ask=0
web_max_ask=0
web_errors=0
if [[ -s "${WEB_HEARTBEAT_FILE}" ]]; then
  heartbeat_age=$((now_epoch - $(stat -c %Y "${WEB_HEARTBEAT_FILE}")))
  IFS=$'\t' read -r web_state web_samples web_gaps web_min_bid web_max_bid web_min_ask web_max_ask web_errors < <(
    python3 - "${WEB_HEARTBEAT_FILE}" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
print('\t'.join(str(d.get(k,0)) for k in ('status','samples','gapSamples','minBids','maxBids','minAsks','maxAsks','pageErrorCount')))
PY
  )
elif [[ "${monitor_state}" == "running" && "${monitor_started_epoch}" -gt 0 && "${monitor_age}" -le "${WEB_STALE_SECONDS}" ]]; then
  heartbeat_age="${monitor_age}"
  web_state=warming
fi
(( heartbeat_age >= 0 && heartbeat_age <= WEB_STALE_SECONDS )) || issues+=("web_heartbeat_stale_${heartbeat_age}s")
[[ "${web_state}" != "error" ]] || issues+=("web_monitor_error")
if (( web_samples >= 20 )); then
  (( web_min_bid == 10 && web_max_bid == 10 && web_min_ask == 10 && web_max_ask == 10 )) ||
    issues+=("web_depth_${web_min_bid}-${web_max_bid}_${web_min_ask}-${web_max_ask}")
  (( web_gaps == 0 )) || issues+=("web_gap_samples_${web_gaps}")
  (( web_errors == 0 )) || issues+=("web_page_errors_${web_errors}")
fi

metrics_line="$(tail -n 1 "${METRICS_FILE}" 2>/dev/null || true)"
accepted=0; rejected=0; gaps=0; auth_refreshes=0; bid_levels=0; ask_levels=0; web_http=0; robot_metric=MISSING
if [[ -n "${metrics_line}" && "${metrics_line}" != time,* ]]; then
  IFS=, read -r _ bid_levels ask_levels robot_metric web_http accepted rejected gaps auth_refreshes <<<"${metrics_line}"
else
  issues+=("load_metrics_missing")
fi
(( bid_levels >= VISIBLE_DEPTH && ask_levels >= VISIBLE_DEPTH )) || issues+=("visible_market_depth_${bid_levels}_${ask_levels}")
[[ "${robot_metric}" == "RUNNING" ]] || issues+=("robot_metric_${robot_metric}")
[[ "${web_http}" == "200" ]] || issues+=("web_http_${web_http}")

previous_accepted=0; previous_rejected=0; previous_gaps=0; previous_auth=0
if [[ -s "${COUNTER_FILE}" ]]; then
  read -r previous_accepted previous_rejected previous_gaps previous_auth <"${COUNTER_FILE}" || true
fi
rejected_delta="$(positive_delta "${rejected}" "${previous_rejected}")"
gap_delta="$(positive_delta "${gaps}" "${previous_gaps}")"
auth_delta="$(positive_delta "${auth_refreshes}" "${previous_auth}")"
(( rejected_delta == 0 )) || issues+=("order_rejections_delta_${rejected_delta}")
(( gap_delta == 0 )) || issues+=("active_order_gap_delta_${gap_delta}")
printf '%s %s %s %s\n' "${accepted}" "${rejected}" "${gaps}" "${auth_refreshes}" >"${COUNTER_FILE}"

robot_row="$(mysql_exec -e "SELECT runtime_status,open_order_count,COALESCE(last_error_code,''),COALESCE(last_error_message,'') FROM dc.dc_tenant_robot WHERE location='${LOCATION}' AND robot_id='${ROBOT_ID}' LIMIT 1;" dc 2>/dev/null || true)"
IFS=$'\t' read -r robot_status robot_orders robot_error_code robot_error_message <<<"${robot_row}"
[[ "${robot_status:-MISSING}" == "RUNNING" ]] || issues+=("robot_status_${robot_status:-MISSING}")
[[ "${robot_orders:-0}" == "40" ]] || issues+=("robot_open_orders_${robot_orders:-0}")
persisted_robot_active="$(mysql_exec -e "SELECT COUNT(*) FROM dc.dc_orders WHERE location='${LOCATION}' AND user_id='${ROBOT_USER}' AND clord_id LIKE 'RBcontinuousd%' AND ord_status IN ('New','Partially_Filled','Pending_Cancel');" dc 2>/dev/null || echo -1)"
[[ "${persisted_robot_active}" == "0" ]] || issues+=("persisted_robot_active_orders_${persisted_robot_active}")

snapshot_tmp="${SNAPSHOT_FILE}.$$"
python3 - "${snapshot_tmp}" "${timestamp}" "${load_pid}" "${monitor_state}" "${heartbeat_age}" \
  "${robot_status:-MISSING}" "${robot_orders:-0}" "${bid_levels}" "${ask_levels}" "${web_http}" \
  "${accepted}" "${rejected}" "${gaps}" "${auth_refreshes}" "${auth_delta}" "${web_state}" \
  "${web_samples}" "${web_min_bid}" "${web_max_bid}" "${web_min_ask}" "${web_max_ask}" \
  "${web_gaps}" "${web_errors}" "${#issues[@]}" <<'PY'
import json,sys
(out,timestamp,load_pid,monitor_state,heartbeat_age,robot_status,robot_orders,bids,asks,http,
 accepted,rejected,gaps,auth,auth_delta,web_state,web_samples,web_min_bid,web_max_bid,
 web_min_ask,web_max_ask,web_gaps,web_errors,issue_count)=sys.argv[1:]
def integer(value):
    try: return int(value)
    except Exception: return 0
d={"time":timestamp,"healthy":issue_count=="0","loadPid":integer(load_pid),
   "monitorState":monitor_state,"heartbeatAgeSeconds":integer(heartbeat_age),
   "robot":{"status":robot_status,"openOrders":integer(robot_orders)},
   "activeOrderDepth":{"bids":integer(bids),"asks":integer(asks)},"webHttp":integer(http),
   "load":{"accepted":integer(accepted),"rejected":integer(rejected),"gaps":integer(gaps),
           "authRefreshes":integer(auth),"authRefreshDelta":integer(auth_delta)},
   "web":{"status":web_state,"samples":integer(web_samples),"minBids":integer(web_min_bid),
          "maxBids":integer(web_max_bid),"minAsks":integer(web_min_ask),"maxAsks":integer(web_max_ask),
          "gaps":integer(web_gaps),"pageErrors":integer(web_errors)}}
with open(out,'w') as f: json.dump(d,f,separators=(',',':')); f.write('\n')
PY
mv "${snapshot_tmp}" "${SNAPSHOT_FILE}"

signature="$(IFS=';'; printf '%s' "${issues[*]:-}")"
previous_signature="$(cat "${LAST_ALERT_FILE}" 2>/dev/null || true)"
if [[ -n "${signature}" ]]; then
  if [[ "${signature}" != "${previous_signature}" ]]; then
    printf '%s ALERT %s\n' "${timestamp}" "${signature}" >>"${ALERT_LOG}"
    logger -t dc-saas-robot-soak "ALERT ${signature}" 2>/dev/null || true
  fi
  printf '%s' "${signature}" >"${LAST_ALERT_FILE}"
  log "UNHEALTHY: ${signature}"
  exit 1
fi

if [[ -n "${previous_signature}" ]]; then
  printf '%s RECOVERED previous=%s\n' "${timestamp}" "${previous_signature}" >>"${ALERT_LOG}"
  logger -t dc-saas-robot-soak "RECOVERED ${previous_signature}" 2>/dev/null || true
fi
: >"${LAST_ALERT_FILE}"
log "HEALTHY robot=${robot_status}/${robot_orders} active=${bid_levels}+${ask_levels} persisted=0 web=${web_min_bid}-${web_max_bid}+${web_min_ask}-${web_max_ask} accepted=${accepted} rejected=${rejected} auth_refresh_delta=${auth_delta}"
