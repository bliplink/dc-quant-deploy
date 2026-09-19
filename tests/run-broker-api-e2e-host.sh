#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${DEPLOY_DIR}/.env.prod}"

log() {
  printf '[broker-api-e2e] %s\n' "$*"
}

die() {
  printf '[broker-api-e2e] ERROR: %s\n' "$*" >&2
  exit 1
}

required() {
  local name="$1"
  [[ -n "${!name:-}" ]] || die "${name} is required"
}

[[ -r "${ENV_FILE}" ]] || die "Cannot read ${ENV_FILE}"
command -v docker >/dev/null 2>&1 || die "docker is required"
command -v python3 >/dev/null 2>&1 || die "python3 is required"

set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a

for name in   BROKER_E2E_LOCATION BROKER_E2E_ACTOR_USER_ID BROKER_E2E_API_KEY BROKER_E2E_API_SECRET   BROKER_E2E_MAKER_CUSTOMER_ID BROKER_E2E_TAKER_CUSTOMER_ID   BROKER_E2E_FOREIGN_LOCATION BROKER_E2E_FOREIGN_CUSTOMER_ID; do
  required "${name}"
done

[[ "${BROKER_E2E_LOCATION}" != "${BROKER_E2E_FOREIGN_LOCATION}" ]] ||
  die "foreign location must differ from broker location"
[[ "${BROKER_E2E_MAKER_CUSTOMER_ID}" != "${BROKER_E2E_TAKER_CUSTOMER_ID}" ]] ||
  die "maker and taker customers must differ"

mysql_exec() {
  docker exec -i -e MYSQL_PWD="${MYSQL_PASSWORD}" dc-saas-mysql     mysql -u"${MYSQL_USERNAME}" -N "$@"
}

robot_image_id="$(docker inspect --format '{{.Image}}' dc-saas-robotsvr 2>/dev/null || true)"
[[ -n "${robot_image_id}" ]] || die "dc-saas-robotsvr is not deployed"

run_id="${BROKER_E2E_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
deposit="${BROKER_E2E_DEPOSIT:-100000}"
withdrawal="${BROKER_E2E_WITHDRAWAL:-100}"

log "Running Broker API through the exact deployed RobotSvr image ${robot_image_id}."
set +e
broker_output="$(docker run --rm --network host   -e MAIN_CLASS=com.app.dc.robot.BrokerApiE2ERunner   -e JAVA_OPTS='-server -Xms32m -Xmx128m -Xmn32m'   -e BROKER_E2E_GATEWAY_HTTP_URL="http://127.0.0.1:${GW_HTTP_PORT}/api"   -e BROKER_E2E_GATEWAY_HOST=127.0.0.1   -e BROKER_E2E_GATEWAY_TCP_PORT="${GW_TCP_PORT}"   -e BROKER_E2E_LOCATION="${BROKER_E2E_LOCATION}"   -e BROKER_E2E_ACTOR_USER_ID="${BROKER_E2E_ACTOR_USER_ID}"   -e BROKER_E2E_API_KEY="${BROKER_E2E_API_KEY}"   -e BROKER_E2E_API_SECRET="${BROKER_E2E_API_SECRET}"   -e BROKER_E2E_MAKER_CUSTOMER_ID="${BROKER_E2E_MAKER_CUSTOMER_ID}"   -e BROKER_E2E_TAKER_CUSTOMER_ID="${BROKER_E2E_TAKER_CUSTOMER_ID}"   -e BROKER_E2E_FOREIGN_LOCATION="${BROKER_E2E_FOREIGN_LOCATION}"   -e BROKER_E2E_FOREIGN_CUSTOMER_ID="${BROKER_E2E_FOREIGN_CUSTOMER_ID}"   -e BROKER_E2E_SYMBOL="${BROKER_E2E_SYMBOL:-BTCUSDT}"   -e BROKER_E2E_MARKET_INDICATOR="${BROKER_E2E_MARKET_INDICATOR:-4}"   -e BROKER_E2E_PRICE="${BROKER_E2E_PRICE:-60000}"   -e BROKER_E2E_QTY="${BROKER_E2E_QTY:-0.001}"   -e BROKER_E2E_DEPOSIT="${deposit}"   -e BROKER_E2E_WITHDRAWAL="${withdrawal}"   -e BROKER_E2E_RUN_ID="${run_id}"   "${robot_image_id}" 2>&1)"
runner_rc=$?
set -e
printf '%s\n' "${broker_output}"
(( runner_rc == 0 )) || die "Broker API runner failed with exit code ${runner_rc}"

summary="$(printf '%s\n' "${broker_output}" | python3 -c '
import json,sys
found=None
for raw in sys.stdin:
    raw=raw.strip()
    if not raw.startswith("{"):
        continue
    try:
        obj=json.loads(raw)
    except Exception:
        continue
    if obj.get("result")=="PASS":
        found=obj
if found is None:
    raise SystemExit(1)
print(json.dumps(found,separators=(",",":")))
')" || die "Broker runner did not emit a PASS summary"

maker_clordid="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["makerClOrdId"])' "${summary}")"
taker_clordid="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["takerClOrdId"])' "${summary}")"
[[ "$(python3 -c 'import json,sys; print(str(json.loads(sys.argv[1])["foreignCustomerRejected"]).lower())' "${summary}")" == "true" ]] ||
  die "foreign tenant customer isolation was not verified"
[[ "$(python3 -c 'import json,sys; print(str(json.loads(sys.argv[1])["reconnected"]).lower())' "${summary}")" == "true" ]] ||
  die "broker reconnect was not verified"

log "Verifying authoritative cash and execution persistence."
db_result="$(mysql_exec dc -e "
SELECT COUNT(*) FROM dc_users_posting
 WHERE location='${BROKER_E2E_LOCATION}'
   AND user_id='${BROKER_E2E_MAKER_CUSTOMER_ID}'
   AND type=1 AND amount='${deposit}';
SELECT COUNT(*) FROM dc_users_posting
 WHERE location='${BROKER_E2E_LOCATION}'
   AND user_id='${BROKER_E2E_TAKER_CUSTOMER_ID}'
   AND type=1 AND amount='${deposit}';
SELECT COUNT(*) FROM dc_users_posting
 WHERE location='${BROKER_E2E_LOCATION}'
   AND user_id='${BROKER_E2E_MAKER_CUSTOMER_ID}'
   AND type=2 AND amount='${withdrawal}';
SELECT COUNT(*) FROM dc_orders_execorders
 WHERE location='${BROKER_E2E_LOCATION}'
   AND user_id='${BROKER_E2E_MAKER_CUSTOMER_ID}'
   AND clordid='${maker_clordid}' AND last_qty > 0;
SELECT COUNT(*) FROM dc_orders_execorders
 WHERE location='${BROKER_E2E_LOCATION}'
   AND user_id='${BROKER_E2E_TAKER_CUSTOMER_ID}'
   AND clordid='${taker_clordid}' AND last_qty > 0;
")"
mapfile -t rows <<<"${db_result}"
[[ "${#rows[@]}" -eq 5 ]] || die "Unexpected Broker DB verification output: ${db_result}"
for i in 0 1 2 3 4; do
  (( rows[i] >= 1 )) || die "Broker DB assertion ${i} failed: ${db_result}"
done

log "PASS: Broker API customer management/trading/cash/reconnect/isolation flow succeeded."
