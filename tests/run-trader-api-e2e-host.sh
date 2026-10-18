#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${DEPLOY_DIR}/.env.prod}"

log() { printf '[trader-api-e2e] %s\n' "$*"; }
die() { printf '[trader-api-e2e] ERROR: %s\n' "$*" >&2; exit 1; }
required() { [[ -n "${!1:-}" ]] || die "$1 is required"; }

[[ -r "${ENV_FILE}" ]] || die "Cannot read ${ENV_FILE}"
command -v docker >/dev/null || die 'docker is required'
command -v python3 >/dev/null || die 'python3 is required'
set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a

for name in TRADER_E2E_LOCATION TRADER_E2E_MAKER_USER_ID TRADER_E2E_MAKER_API_KEY \
    TRADER_E2E_MAKER_API_SECRET TRADER_E2E_TAKER_USER_ID TRADER_E2E_TAKER_API_KEY \
    TRADER_E2E_TAKER_API_SECRET; do
  required "${name}"
done
[[ "${TRADER_E2E_LOCATION}" =~ ^[A-Z0-9]{6}$ ]] || die 'invalid test location'
[[ "${TRADER_E2E_MAKER_USER_ID}" != "${TRADER_E2E_TAKER_USER_ID}" ]] || die 'maker and taker must differ'
robot_image_id="$(docker inspect --format '{{.Image}}' dc-saas-robotsvr 2>/dev/null || true)"
[[ -n "${robot_image_id}" ]] || die 'dc-saas-robotsvr is not deployed'
run_id="${TRADER_E2E_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"

log "Running Trade API strategy client through deployed image ${robot_image_id}."
set +e
runner_output="$(docker run --rm --network host \
  -e MAIN_CLASS=com.app.dc.robot.TraderApiE2ERunner \
  -e JAVA_OPTS='-server -Xms32m -Xmx128m -Xmn32m' \
  -e TRADER_E2E_GATEWAY_HTTP_URL="http://127.0.0.1:${GW_HTTP_PORT}/api" \
  -e TRADER_E2E_GATEWAY_HOST=127.0.0.1 \
  -e TRADER_E2E_GATEWAY_TCP_PORT="${GW_TCP_PORT}" \
  -e TRADER_E2E_LOCATION="${TRADER_E2E_LOCATION}" \
  -e TRADER_E2E_MAKER_USER_ID="${TRADER_E2E_MAKER_USER_ID}" \
  -e TRADER_E2E_MAKER_API_KEY \
  -e TRADER_E2E_MAKER_API_SECRET \
  -e TRADER_E2E_TAKER_USER_ID="${TRADER_E2E_TAKER_USER_ID}" \
  -e TRADER_E2E_TAKER_API_KEY \
  -e TRADER_E2E_TAKER_API_SECRET \
  -e TRADER_E2E_SYMBOL="${TRADER_E2E_SYMBOL:-BTCUSDT}" \
  -e TRADER_E2E_MARKET_INDICATOR="${TRADER_E2E_MARKET_INDICATOR:-4}" \
  -e TRADER_E2E_PRICE="${TRADER_E2E_PRICE:-60000}" \
  -e TRADER_E2E_QTY="${TRADER_E2E_QTY:-0.001}" \
  -e TRADER_E2E_RUN_ID="${run_id}" \
  "${robot_image_id}" 2>&1)"
runner_rc=$?
set -e
printf '%s\n' "${runner_output}"
(( runner_rc == 0 )) || die "Trade API runner failed with exit code ${runner_rc}"

summary="$(printf '%s\n' "${runner_output}" | python3 -c '
import json, sys
result = None
for raw in sys.stdin:
    if not raw.startswith("{"):
        continue
    try:
        item = json.loads(raw)
    except ValueError:
        continue
    if item.get("result") == "PASS":
        result = item
if result is None or not result.get("reconnected") or not result.get("makerExecId") or not result.get("takerExecId"):
    raise SystemExit(1)
print(json.dumps(result, separators=(",", ":")))
')" || die 'Trade API runner did not prove executions and reconnect'

maker_clordid="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["makerClOrdId"])' "${summary}")"
taker_clordid="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["takerClOrdId"])' "${summary}")"
for value in "${maker_clordid}" "${taker_clordid}"; do
  [[ "${value}" =~ ^[A-Za-z0-9_-]+$ ]] || die 'invalid runner order id'
done

log 'Checking eventual order/execution projections for both strategy accounts.'
for ((attempt=1; attempt<=30; attempt++)); do
  counts="$(docker exec -i -e MYSQL_PWD="${MYSQL_PASSWORD}" dc-saas-mysql \
    mysql -u"${MYSQL_USERNAME}" -N dc -e "
SELECT COUNT(*) FROM dc_orders_execorders e JOIN dc_orders o
 ON o.location=e.location AND o.user_id=e.user_id AND o.order_id=e.order_id
 WHERE e.location='${TRADER_E2E_LOCATION}' AND e.user_id='${TRADER_E2E_MAKER_USER_ID}'
 AND o.clord_id='${maker_clordid}' AND e.last_qty > 0;
SELECT COUNT(*) FROM dc_orders_execorders e JOIN dc_orders o
 ON o.location=e.location AND o.user_id=e.user_id AND o.order_id=e.order_id
 WHERE e.location='${TRADER_E2E_LOCATION}' AND e.user_id='${TRADER_E2E_TAKER_USER_ID}'
 AND o.clord_id='${taker_clordid}' AND e.last_qty > 0;")"
  if python3 -c 'import sys; a=[int(x) for x in sys.stdin.read().split()]; raise SystemExit(0 if len(a)==2 and min(a)>=1 else 1)' <<<"${counts}"; then
    log 'PASS: public Trade API strategy, private executions, reconnect and projections.'
    exit 0
  fi
  (( attempt == 30 )) || sleep 1
done
die "Trade API projections did not converge: ${counts}"
