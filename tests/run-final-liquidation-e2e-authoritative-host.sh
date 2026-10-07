#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${DEPLOY_DIR}/.env.prod}"
RUN_ID="${FINAL_LIQ_E2E_RUN_ID:-$(date +%Y%m%d%H%M%S)}"
LIQ_LOCATION="${FINAL_LIQ_E2E_LOCATION:-FINAL_LIQ_V2_E2E_${RUN_ID}}"
OTHER_LOCATION="${FINAL_LIQ_E2E_OTHER_LOCATION:-${LIQ_LOCATION}_FOREIGN}"
SCENARIO="${FINAL_LIQ_E2E_SCENARIO:-mixed}"

LIQ_USER="${FINAL_LIQ_E2E_USER:-final_liquidated}_${RUN_ID}"
OPEN_USER="${FINAL_LIQ_E2E_OPEN_USER:-final_open}_${RUN_ID}"
MAKER_USER="${FINAL_LIQ_E2E_MAKER:-final_maker}_${RUN_ID}"
ADL_USER="${FINAL_LIQ_E2E_ADL_USER:-final_adl}_${RUN_ID}"
FOREIGN_USER="${FINAL_LIQ_E2E_FOREIGN_USER:-final_foreign}_${RUN_ID}"
FOREIGN_OPEN_USER="${FINAL_LIQ_E2E_FOREIGN_OPEN_USER:-final_foreign_open}_${RUN_ID}"

liq_test_stopped=false
override_installed=false
override_session=""

log() { printf '[final-liq-e2e] %s\n' "$*"; }
die() { printf '[final-liq-e2e] ERROR: %s\n' "$*" >&2; exit 1; }
safe_identifier() { [[ "$1" =~ ^[A-Za-z0-9_.-]+$ ]]; }

[[ -r "${ENV_FILE}" ]] || die "Cannot read ${ENV_FILE}"
command -v python3 >/dev/null 2>&1 || die "python3 is required"
for value in "${RUN_ID}" "${LIQ_LOCATION}" "${OTHER_LOCATION}" "${LIQ_USER}" "${OPEN_USER}" \
  "${MAKER_USER}" "${ADL_USER}" "${FOREIGN_USER}" "${FOREIGN_OPEN_USER}"; do
  safe_identifier "${value}" || die "Unsupported identifier: ${value}"
done
[[ "${LIQ_LOCATION}" != "${OTHER_LOCATION}" ]] || die "Final-liquidation locations must differ"
case "${SCENARIO}" in
  mixed|full_fill|full_insurance|adl_multi) ;;
  *) die "FINAL_LIQ_E2E_SCENARIO must be mixed, full_fill, full_insurance or adl_multi" ;;
esac

set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a
E2E_PASSWORD="${E2E_PASSWORD:-${LOGIN_DEFAULT_PASSWORD:-}}"
[[ -n "${E2E_PASSWORD}" ]] || die "E2E_PASSWORD or LOGIN_DEFAULT_PASSWORD is required"
[[ "${MDSVR_E2E_MARK_PRICE_OVERRIDE_ENABLED:-false}" == "true" ]] ||
  die "MDSVR_E2E_MARK_PRICE_OVERRIDE_ENABLED=true is required"
[[ -n "${MDSVR_E2E_MARK_PRICE_OVERRIDE_TOKEN:-}" ]] ||
  die "MDSVR_E2E_MARK_PRICE_OVERRIDE_TOKEN is required"

# shellcheck source=liquidation-e2e-common.sh
. "${SCRIPT_DIR}/liquidation-e2e-common.sh"

cleanup() {
  if [[ "${override_installed}" == "true" ]]; then
    e2e_clear_mark_override "${LIQ_LOCATION}" "${override_session}" || true
  fi
  if [[ "${liq_test_stopped}" == "true" ]]; then
    docker start dc-saas-liqsvr >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

password_hash="$(printf '%s' "${E2E_PASSWORD}" | sha256sum | awk '{print $1}')"

provision_users() {
  e2e_mysql dc <<SQL
INSERT INTO dc_users
  (user_id,user_name,name,password,user_type,enable,create_time,update_time,
   enable_trade,enable_cash_in,enable_cash_out,close_by,location)
VALUES
  ('${LIQ_USER}','${LIQ_USER}','Final Liq Target','${password_hash}','1','1',NOW(),NOW(),'1','1','1','FINAL_LIQ_E2E','${LIQ_LOCATION}'),
  ('${OPEN_USER}','${OPEN_USER}','Final Liq Peer','${password_hash}','1','1',NOW(),NOW(),'1','1','1','FINAL_LIQ_E2E','${LIQ_LOCATION}'),
  ('${MAKER_USER}','${MAKER_USER}','Final Liq Maker','${password_hash}','1','1',NOW(),NOW(),'1','1','1','FINAL_LIQ_E2E','${LIQ_LOCATION}'),
  ('${ADL_USER}','${ADL_USER}','Final Liq ADL','${password_hash}','1','1',NOW(),NOW(),'1','1','1','FINAL_LIQ_E2E','${LIQ_LOCATION}'),
  ('${FOREIGN_USER}','${FOREIGN_USER}','Final Liq Foreign','${password_hash}','1','1',NOW(),NOW(),'1','1','1','FINAL_LIQ_E2E','${OTHER_LOCATION}'),
  ('${FOREIGN_OPEN_USER}','${FOREIGN_OPEN_USER}','Final Liq Foreign Peer','${password_hash}','1','1',NOW(),NOW(),'1','1','1','FINAL_LIQ_E2E','${OTHER_LOCATION}')
ON DUPLICATE KEY UPDATE
  password=VALUES(password),enable='1',enable_trade='1',enable_cash_in='1',
  enable_cash_out='1',location=VALUES(location),update_time=NOW();
SQL
}

wait_liq_startup_image() {
  local baseline="$1" count
  for _ in $(seq 1 120); do
    count="$(docker logs dc-saas-liqsvr 2>&1 | grep -c 'TradeSvr partition startup image replayed, topic:dc.trade.position.\*\*' || true)"
    if (( count > baseline )); then
      return 0
    fi
    sleep 1
  done
  docker logs --tail 220 dc-saas-liqsvr >&2 || true
  return 1
}

parse_long_risk() {
  python3 -c '
import json,sys
from decimal import Decimal
d=json.load(sys.stdin); p=d.get("data") or {}
qty=Decimal(str(p.get("LongPosition",p.get("longPosition",0))))
avg=Decimal(str(p.get("LongAverage",p.get("longAverage",0))))
liq=Decimal(str(p.get("LongLiqPrice",p.get("longLiqPrice",0))))
bank=Decimal(str(p.get("LongBankruptcyPrice",p.get("longBankruptcyPrice",0))))
status=str(p.get("PositionStatus",p.get("positionStatus","")))
print(f"{qty}\t{avg}\t{liq}\t{bank}\t{status}")
'
}

wait_position_side() {
  local location="$1" user="$2" token="$3" side="$4" expected="$5" response value
  for _ in $(seq 1 100); do
    response="$(e2e_query_position "${location}" "${user}" "${token}" 2>/dev/null || true)"
    value="$(printf '%s' "${response}" | python3 -c '
import json,sys
from decimal import Decimal
side=sys.argv[1]
try:
 d=json.load(sys.stdin); p=d.get("data") or {}
 key="LongPosition" if side=="Long" else "ShortPosition"
 alt="longPosition" if side=="Long" else "shortPosition"
 print(Decimal(str(p.get(key,p.get(alt,0)))))
except Exception:
 print(Decimal(0))
' "${side}" 2>/dev/null || printf '0')"
    [[ "${value}" == "${expected}" ]] && return 0
    sleep 0.5
  done
  die "${user}@${location} ${side} position did not reach ${expected}; last=${value}"
}

seed_insurance_fund() {
  local amount="$1"
  e2e_mysql dc <<SQL
DELETE FROM dc_insurance_position WHERE location='${LIQ_LOCATION}' AND security_id='BTCUSDT';
INSERT INTO dc_insurance_fund(location,security_id,balance,update_time)
VALUES('${LIQ_LOCATION}','BTCUSDT',${amount},NOW())
ON DUPLICATE KEY UPDATE balance=VALUES(balance),update_time=VALUES(update_time);
SQL
}

final_order_row() {
  local expected_status="$1"
  e2e_mysql -e "SELECT
      JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.orderId')),
      JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.clOrderId'))
    FROM dc.dc_order_projection_event
    WHERE JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.location'))='${LIQ_LOCATION}'
      AND JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.userId'))='${LIQ_USER}'
      AND JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.securityId'))='BTCUSDT'
      AND JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.closeBy'))='liq_v2'
      AND JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.orderStatus'))='${expected_status}'
      AND JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.orderType'))='Limit'
      AND JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.timeInForce'))='IOC'
      AND JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.reduceOnly'))='true'
      AND JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.demo'))='1'
    ORDER BY create_time DESC,journal_seq DESC LIMIT 1;" dc
}

log "Stopping LiqSvr while authoritative final-liquidation positions are constructed."
docker stop dc-saas-liqsvr >/dev/null
liq_test_stopped=true

log "Provisioning LoginSvr identities only; user balances/positions remain service-owned."
provision_users
docker restart dc-saas-loginsvr >/dev/null
e2e_wait_port "${LOGINSVR_GW_PORT}" dc-saas-loginsvr || die "LoginSvr did not become ready"
e2e_wait_route "${LIQ_LOCATION}" OrderSvr || die "OrderSvr not routable"
e2e_wait_route "${LIQ_LOCATION}" TradeSvr || die "TradeSvr not routable"

liq_session="$(e2e_login_user "${LIQ_USER}" "${LIQ_LOCATION}" FINAL_LIQ "${E2E_PASSWORD}")"
open_session="$(e2e_login_user "${OPEN_USER}" "${LIQ_LOCATION}" FINAL_LIQ "${E2E_PASSWORD}")"
maker_session="$(e2e_login_user "${MAKER_USER}" "${LIQ_LOCATION}" FINAL_LIQ "${E2E_PASSWORD}")"
adl_session="$(e2e_login_user "${ADL_USER}" "${LIQ_LOCATION}" FINAL_LIQ "${E2E_PASSWORD}")"
foreign_session="$(e2e_login_user "${FOREIGN_USER}" "${OTHER_LOCATION}" FINAL_LIQ "${E2E_PASSWORD}")"
foreign_open_session="$(e2e_login_user "${FOREIGN_OPEN_USER}" "${OTHER_LOCATION}" FINAL_LIQ "${E2E_PASSWORD}")"
override_session="${liq_session}"

e2e_fund_trade_account "${LIQ_USER}" "${liq_session}" "${LIQ_LOCATION}" 10 || die "Could not fund target"
e2e_fund_trade_account "${OPEN_USER}" "${open_session}" "${LIQ_LOCATION}" 100000 || die "Could not fund peer"
e2e_fund_trade_account "${MAKER_USER}" "${maker_session}" "${LIQ_LOCATION}" 100000 || die "Could not fund maker"
e2e_fund_trade_account "${ADL_USER}" "${adl_session}" "${LIQ_LOCATION}" 100 || die "Could not fund ADL candidate"
e2e_fund_trade_account "${FOREIGN_USER}" "${foreign_session}" "${OTHER_LOCATION}" 100 || die "Could not fund foreign"
e2e_fund_trade_account "${FOREIGN_OPEN_USER}" "${foreign_open_session}" "${OTHER_LOCATION}" 100000 || die "Could not fund foreign peer"

for pair in \
  "${liq_session}|${LIQ_LOCATION}" "${open_session}|${LIQ_LOCATION}" \
  "${maker_session}|${LIQ_LOCATION}" "${adl_session}|${LIQ_LOCATION}" \
  "${foreign_session}|${OTHER_LOCATION}" "${foreign_open_session}|${OTHER_LOCATION}"; do
  IFS='|' read -r token location <<<"${pair}"
  e2e_set_leverage_100 "${token}" "${location}" || die "Could not set leverage in ${location}"
done

entry_mark="$(e2e_query_mark "${LIQ_LOCATION}")"
entry_price="$(python3 - "${entry_mark}" <<'PY'
from decimal import Decimal, ROUND_HALF_UP
import sys
print(Decimal(sys.argv[1]).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
PY
)"
foreign_mark_before="$(e2e_query_mark "${OTHER_LOCATION}")"

target_peer_user="${OPEN_USER}"
target_peer_session="${open_session}"
if [[ "${SCENARIO}" == "mixed" ]]; then
  target_peer_user="${ADL_USER}"
  target_peer_session="${adl_session}"
fi

if [[ "${SCENARIO}" == "adl_multi" ]]; then
  high_peer_clid="FINAL-ADL-HIGH-${RUN_ID}"
  low_peer_clid="FINAL-ADL-LOW-${RUN_ID}"
  target_high_clid="FINAL-TARGET-HIGH-${RUN_ID}"
  target_low_clid="FINAL-TARGET-LOW-${RUN_ID}"
  log "Creating two real profitable SHORT ADL candidates and a 0.0002 BTC target LONG."
  e2e_place_open_order "${LIQ_LOCATION}" "${ADL_USER}" "${adl_session}" Sell 0.0001 "${entry_price}" GTC "${high_peer_clid}" || die "Could not rest high-rank ADL candidate"
  e2e_wait_order_status "${LIQ_LOCATION}" "${high_peer_clid}" New || die "High-rank ADL candidate did not rest"
  e2e_place_open_order "${LIQ_LOCATION}" "${OPEN_USER}" "${open_session}" Sell 0.0001 "${entry_price}" GTC "${low_peer_clid}" || die "Could not rest low-rank ADL candidate"
  e2e_wait_order_status "${LIQ_LOCATION}" "${low_peer_clid}" New || die "Low-rank ADL candidate did not rest"
  e2e_place_open_order "${LIQ_LOCATION}" "${LIQ_USER}" "${liq_session}" Buy 0.0001 "${entry_price}" IOC "${target_high_clid}" || die "Could not open first target slice"
  e2e_wait_order_status "${LIQ_LOCATION}" "${target_high_clid}" Filled || die "First target slice did not fill"
  e2e_place_open_order "${LIQ_LOCATION}" "${LIQ_USER}" "${liq_session}" Buy 0.0001 "${entry_price}" IOC "${target_low_clid}" || die "Could not open second target slice"
  e2e_wait_order_status "${LIQ_LOCATION}" "${target_low_clid}" Filled || die "Second target slice did not fill"
  e2e_wait_order_status "${LIQ_LOCATION}" "${high_peer_clid}" Filled || die "High-rank candidate opening order did not fill"
  e2e_wait_order_status "${LIQ_LOCATION}" "${low_peer_clid}" Filled || die "Low-rank candidate opening order did not fill"
  wait_position_side "${LIQ_LOCATION}" "${LIQ_USER}" "${liq_session}" Long 0.0002
  wait_position_side "${LIQ_LOCATION}" "${ADL_USER}" "${adl_session}" Short 0.0001
  wait_position_side "${LIQ_LOCATION}" "${OPEN_USER}" "${open_session}" Short 0.0001
else
  target_peer_clid="FINAL-PEER-${RUN_ID}"
  target_clid="FINAL-TARGET-${RUN_ID}"
  log "Creating authoritative 0.0002 BTC target long at ${entry_price}; peer=${target_peer_user}."
  e2e_place_open_order "${LIQ_LOCATION}" "${target_peer_user}" "${target_peer_session}" Sell 0.0002 "${entry_price}" GTC "${target_peer_clid}" ||
    die "Could not rest target opening peer"
  e2e_wait_order_status "${LIQ_LOCATION}" "${target_peer_clid}" New ||
    die "Target opening peer did not rest"
  e2e_place_open_order "${LIQ_LOCATION}" "${LIQ_USER}" "${liq_session}" Buy 0.0002 "${entry_price}" IOC "${target_clid}" ||
    die "Could not open target long"
  e2e_wait_order_status "${LIQ_LOCATION}" "${target_clid}" Filled || die "Target open did not fill"
  e2e_wait_order_status "${LIQ_LOCATION}" "${target_peer_clid}" Filled || die "Target peer did not fill"
  wait_position_side "${LIQ_LOCATION}" "${LIQ_USER}" "${liq_session}" Long 0.0002
fi

foreign_entry="$(python3 - "${foreign_mark_before}" <<'PY'
from decimal import Decimal, ROUND_HALF_UP
import sys
print(Decimal(sys.argv[1]).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
PY
)"
foreign_peer_clid="FINAL-FOREIGN-PEER-${RUN_ID}"
foreign_clid="FINAL-FOREIGN-${RUN_ID}"
log "Creating real foreign-tenant 0.0002 BTC SHORT for isolation proof."
e2e_place_open_order "${OTHER_LOCATION}" "${FOREIGN_OPEN_USER}" "${foreign_open_session}" Buy 0.0002 "${foreign_entry}" GTC "${foreign_peer_clid}" ||
  die "Could not rest foreign peer"
e2e_wait_order_status "${OTHER_LOCATION}" "${foreign_peer_clid}" New || die "Foreign peer did not rest"
e2e_place_open_order "${OTHER_LOCATION}" "${FOREIGN_USER}" "${foreign_session}" Sell 0.0002 "${foreign_entry}" IOC "${foreign_clid}" ||
  die "Could not open foreign short"
e2e_wait_order_status "${OTHER_LOCATION}" "${foreign_clid}" Filled || die "Foreign open did not fill"
wait_position_side "${OTHER_LOCATION}" "${FOREIGN_USER}" "${foreign_session}" Short 0.0002

position_response="$(e2e_query_position "${LIQ_LOCATION}" "${LIQ_USER}" "${liq_session}")"
IFS=$'\t' read -r target_qty target_avg target_liq target_bank target_status < <(
  printf '%s' "${position_response}" | parse_long_risk
)
[[ "${target_qty}" == "0.0002" ]] || die "Unexpected target quantity before collateral adjustment: ${target_qty}"

account_response="$(e2e_query_account "${LIQ_LOCATION}" "${LIQ_USER}" "${liq_session}")"
current_mark="$(e2e_query_mark "${LIQ_LOCATION}")"
withdraw_amount="$(python3 - "${account_response}" "${position_response}" "${current_mark}" <<'PY'
import json,sys
from decimal import Decimal
account=(json.loads(sys.argv[1]).get("data") or {})
pos=(json.loads(sys.argv[2]).get("data") or {})
mark=Decimal(sys.argv[3])
balance=Decimal(str(account.get("Balance",account.get("balance",0))))
used=Decimal(str(account.get("UsedMargin",account.get("usedMargin",0))))
frozen=Decimal(str(account.get("FreezedMargin",account.get("freezedMargin",0))))
commission=Decimal(str(account.get("FreezedCommission",account.get("freezedCommission",0))))
qty=Decimal(str(pos.get("LongPosition",pos.get("longPosition",0))))
avg=Decimal(str(pos.get("LongAverage",pos.get("longAverage",0))))
pnl=qty*(mark-avg)
available=balance-used-frozen-commission+min(pnl,Decimal(0))
reserve=Decimal("0.02")
amount=max(Decimal(0),available-reserve)
print(amount.quantize(Decimal("0.00000001")))
PY
)"
[[ "${withdraw_amount}" != "0.00000000" && "${withdraw_amount}" != "0E-8" ]] ||
  die "No withdrawable collateral remained for final-liquidation setup"
e2e_cash_out "${LIQ_LOCATION}" "${LIQ_USER}" "${liq_session}" "${withdraw_amount}" ||
  die "Could not reduce target collateral"

log "Waiting for authoritative liquidation and bankruptcy prices after collateral adjustment."
for _ in $(seq 1 100); do
  position_response="$(e2e_query_position "${LIQ_LOCATION}" "${LIQ_USER}" "${liq_session}" 2>/dev/null || true)"
  IFS=$'\t' read -r target_qty target_avg target_liq target_bank target_status < <(
    printf '%s' "${position_response}" | parse_long_risk 2>/dev/null || printf '0\t0\t0\t0\t'
  )
  if [[ "${target_qty}" == "0.0002" && "${target_status}" == "1" ]] &&
     python3 - "${target_liq}" "${target_bank}" <<'PY' >/dev/null 2>&1
from decimal import Decimal
import sys
raise SystemExit(0 if Decimal(sys.argv[1]) > 0 and Decimal(sys.argv[2]) > 0 else 1)
PY
  then
    break
  fi
  sleep 0.5
done
[[ "${target_qty}" == "0.0002" && "${target_status}" == "1" ]] ||
  die "TradeSvr did not publish authoritative final-liquidation risk: ${position_response}"

insurance_seed="$(python3 - "${SCENARIO}" "${target_bank}" <<'PY'
from decimal import Decimal
import sys
scenario=sys.argv[1]; bank=Decimal(sys.argv[2])
if scenario=="full_insurance":
    value=bank*Decimal("0.0002")+Decimal("1")
elif scenario=="mixed":
    value=bank*Decimal("0.0001")
else:
    value=Decimal(0)
print(value)
PY
)"
seed_insurance_fund "${insurance_seed}"
log "Insurance fund seeded only as system test state: scenario=${SCENARIO} balance=${insurance_seed}."

if [[ "${SCENARIO}" == "full_fill" ]]; then
  maker_clid="FINAL-MAKER-${RUN_ID}"
  log "Resting full-fill maker bid above bankruptcy bound."
  e2e_place_open_order "${LIQ_LOCATION}" "${MAKER_USER}" "${maker_session}" Buy 0.0002 "${entry_price}" GTC "${maker_clid}" ||
    die "Could not place full-fill maker"
  e2e_wait_order_status "${LIQ_LOCATION}" "${maker_clid}" New || die "Full-fill maker did not rest"
fi

live_mark="$(e2e_query_mark "${LIQ_LOCATION}")"
python3 - "${live_mark}" "${target_liq}" <<'PY' >/dev/null || die "Target became unsafe before controlled mark injection"
from decimal import Decimal
import sys
assert Decimal(sys.argv[1]) > Decimal(sys.argv[2])
PY

unsafe_mark="$(python3 - "${target_liq}" <<'PY'
from decimal import Decimal, ROUND_DOWN
import sys
liq=Decimal(sys.argv[1])
mark=(liq*Decimal("0.998")).quantize(Decimal("0.1"),rounding=ROUND_DOWN)
if mark>=liq: mark=liq-Decimal("0.1")
assert mark>0
print(mark)
PY
)"

startup_before="$(docker logs dc-saas-liqsvr 2>&1 | grep -c 'TradeSvr partition startup image replayed, topic:dc.trade.position.\*\*' || true)"
log "Starting LiqSvr under safe market state; no user login is required by LiqSvr."
docker start dc-saas-liqsvr >/dev/null
liq_test_stopped=false
wait_liq_startup_image "${startup_before}" || die "LiqSvr did not replay authoritative Trade position image"
e2e_wait_route "${LIQ_LOCATION}" OrderSvr || die "OrderSvr route not ready after LiqSvr start"
e2e_wait_route "${LIQ_LOCATION}" TradeSvr || die "TradeSvr route not ready after LiqSvr start"

log "Applying tenant-only unsafe MarkPrice ${unsafe_mark}; foreign tenant remains live."
e2e_set_mark_override "${LIQ_LOCATION}" "${override_session}" "${unsafe_mark}" ||
  die "Could not apply target tenant MarkPrice"
override_installed=true
for _ in $(seq 1 40); do
  seen="$(e2e_query_mark "${LIQ_LOCATION}" 2>/dev/null || true)"
  [[ "${seen}" == "${unsafe_mark}" ]] && break
  sleep 0.25
done
[[ "${seen:-}" == "${unsafe_mark}" ]] || die "Target tenant did not observe unsafe MarkPrice"
foreign_mark_after="$(e2e_query_mark "${OTHER_LOCATION}")"
[[ "${foreign_mark_after}" != "${unsafe_mark}" ]] || die "Tenant MarkPrice override leaked to foreign tenant"

expected_status="Cancelled"
[[ "${SCENARIO}" == "full_fill" ]] && expected_status="Filled"
liquidation_order_id=""
liquidation_clid=""
for _ in $(seq 1 600); do
  row="$(final_order_row "${expected_status}")"
  if [[ -n "${row}" ]]; then
    IFS=$'\t' read -r liquidation_order_id liquidation_clid <<<"${row}"
    break
  fi
  sleep 0.2
done
if [[ -z "${liquidation_order_id}" ]]; then
  docker logs --tail 260 dc-saas-liqsvr >&2 || true
  die "No final liq_v2 Limit/IOC ${expected_status} event appeared in Order projection journal"
fi

e2e_clear_mark_override "${LIQ_LOCATION}" "${override_session}"
override_installed=false
log "Final liquidation order ${liquidation_order_id} reached ${expected_status}; validating ${SCENARIO} settlement."

if [[ "${SCENARIO}" == "full_fill" ]]; then
  for _ in $(seq 1 100); do
    response="$(e2e_query_position "${LIQ_LOCATION}" "${LIQ_USER}" "${liq_session}" 2>/dev/null || true)"
    qty="$(printf '%s' "${response}" | python3 -c 'import json,sys; from decimal import Decimal; d=json.load(sys.stdin); p=d.get("data") or {}; print(Decimal(str(p.get("LongPosition",p.get("longPosition",0)))))' 2>/dev/null || printf '1')"
    [[ "${qty}" == "0" ]] && break
    sleep 0.5
  done
  [[ "${qty}" == "0" ]] || die "Fully-filled final liquidation did not flatten target position"
  transfer_count="$(e2e_mysql -e "SELECT COUNT(*) FROM dc.dc_bankruptcy_transfer WHERE location='${LIQ_LOCATION}' AND liquidation_order_id='${liquidation_order_id}';" dc)"
  [[ "${transfer_count}" == "0" ]] || die "Full-fill scenario unexpectedly entered bankruptcy takeover"
  filled_qty="$(e2e_mysql -e "SELECT JSON_UNQUOTE(JSON_EXTRACT(payload,'$.execution.qty'))
    FROM dc.dc_order_projection_event
    WHERE JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.orderId'))='${liquidation_order_id}'
      AND JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.orderStatus'))='Filled'
    ORDER BY create_time DESC,journal_seq DESC LIMIT 1;" dc)"
  [[ "${filled_qty}" == "0.0002" ]] || die "Full-fill execution quantity mismatch: ${filled_qty}"
elif [[ "${SCENARIO}" == "full_insurance" ]]; then
  completed=0
  for _ in $(seq 1 300); do
    completed="$(e2e_mysql -e "SELECT COUNT(*) FROM dc.dc_bankruptcy_transfer
      WHERE location='${LIQ_LOCATION}' AND liquidation_order_id='${liquidation_order_id}'
        AND liquidation_side='Sell' AND status='INSURANCE_TAKEOVER'
        AND ABS(requested_quantity-0.0002)<0.00000001
        AND ABS(insurance_quantity-0.0002)<0.00000001
        AND ABS(adl_quantity)<0.00000001;" dc)"
    [[ "${completed}" == "1" ]] && break
    sleep 0.2
  done
  [[ "${completed}" == "1" ]] || die "Full insurance takeover did not complete"
  insurance_qty="$(e2e_mysql -e "SELECT quantity FROM dc.dc_insurance_position
    WHERE location='${LIQ_LOCATION}' AND security_id='BTCUSDT' AND position_side='LONG';" dc)"
  [[ "${insurance_qty}" == "0.0002000000000000" || "${insurance_qty}" == "0.0002" ]] ||
    die "Insurance position quantity mismatch: ${insurance_qty}"
elif [[ "${SCENARIO}" == "mixed" ]]; then
  completed=0
  for _ in $(seq 1 400); do
    completed="$(e2e_mysql -e "SELECT COUNT(*) FROM dc.dc_bankruptcy_transfer
      WHERE location='${LIQ_LOCATION}' AND liquidation_order_id='${liquidation_order_id}'
        AND liquidation_side='Sell' AND status='ADL_DONE'
        AND ABS(requested_quantity-0.0002)<0.00000001
        AND ABS(insurance_quantity-0.0001)<0.00000001
        AND ABS(adl_quantity-0.0001)<0.00000001;" dc)"
    [[ "${completed}" == "1" ]] && break
    sleep 0.2
  done
  [[ "${completed}" == "1" ]] || die "Mixed insurance/ADL takeover did not reach ADL_DONE"
  adl_check="$(e2e_mysql -e "SELECT IF(rank_no=1 AND candidate_user_id='${ADL_USER}'
      AND candidate_position_side='SHORT' AND ABS(quantity-0.0001)<0.00000001,1,0)
    FROM dc.dc_adl_execution_v2
    WHERE location='${LIQ_LOCATION}' AND liquidation_order_id='${liquidation_order_id}'
    ORDER BY rank_no LIMIT 1;" dc)"
  [[ "${adl_check}" == "1" ]] || die "Mixed scenario ADL candidate/rank/quantity mismatch"
  wait_position_side "${LIQ_LOCATION}" "${ADL_USER}" "${adl_session}" Short 0.0001
else
  completed=0
  for _ in $(seq 1 400); do
    completed="$(e2e_mysql -e "SELECT COUNT(*) FROM dc.dc_bankruptcy_transfer
      WHERE location='${LIQ_LOCATION}' AND liquidation_order_id='${liquidation_order_id}'
        AND liquidation_side='Sell' AND status='ADL_DONE'
        AND ABS(requested_quantity-0.0002)<0.00000001
        AND ABS(insurance_quantity)<0.00000001
        AND ABS(adl_quantity-0.0002)<0.00000001;" dc)"
    [[ "${completed}" == "1" ]] && break
    sleep 0.2
  done
  [[ "${completed}" == "1" ]] || die "Multi-candidate ADL takeover did not reach ADL_DONE"
  adl_rows="$(e2e_mysql -e "SELECT rank_no,candidate_user_id,candidate_position_side,quantity
    FROM dc.dc_adl_execution_v2
    WHERE location='${LIQ_LOCATION}' AND liquidation_order_id='${liquidation_order_id}'
    ORDER BY rank_no;" dc)"
  python3 - "${adl_rows}" "${ADL_USER}" "${OPEN_USER}" <<'PY' || die "Multi-candidate ADL ranking/quantity mismatch: ${adl_rows}"
from decimal import Decimal
import sys
rows=[line.split('\t') for line in sys.argv[1].splitlines() if line.strip()]
assert len(rows)==2, rows
assert rows[0][0]=='1' and rows[0][1]==sys.argv[2] and rows[0][2]=='SHORT' and Decimal(rows[0][3])==Decimal('0.0001'), rows
assert rows[1][0]=='2' and rows[1][1]==sys.argv[3] and rows[1][2]=='SHORT' and Decimal(rows[1][3])==Decimal('0.0001'), rows
PY
  wait_position_side "${LIQ_LOCATION}" "${ADL_USER}" "${adl_session}" Short 0
  wait_position_side "${LIQ_LOCATION}" "${OPEN_USER}" "${open_session}" Short 0
fi

wait_position_side "${LIQ_LOCATION}" "${LIQ_USER}" "${liq_session}" Long 0
wait_position_side "${OTHER_LOCATION}" "${FOREIGN_USER}" "${foreign_session}" Short 0.0002
foreign_adl="$(e2e_mysql -e "SELECT COUNT(*) FROM dc.dc_adl_execution_v2
  WHERE location='${OTHER_LOCATION}' AND liquidation_order_id='${liquidation_order_id}';" dc)"
[[ "${foreign_adl}" == "0" ]] || die "Cross-tenant ADL execution was created"

log "PASS: ${SCENARIO} final liquidation used real Demo=1 Order/Trade state; final order is authoritative in Order projection journal, bankruptcy/insurance/ADL settled transactionally, and foreign tenant remained untouched."
