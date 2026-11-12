#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
run_dir="${1:?usage: verify-mac-demo-fresh.sh RUN_DIRECTORY}"
generation="$(basename "$run_dir")"
ha_evidence="${2:-}"
ha_timeout="${3:-1900}"
ha_mode="${4:-}"
[[ "$#" -eq 1 || ( "$#" -eq 4 && -n "$ha_evidence" && -f "$ha_evidence/evidence.json"
   && ( "$ha_mode" == funded || "$ha_mode" == order-only ) ) ]]
[[ "$generation" =~ ^mac-demo-[0-9]{8}-[0-9]{6}$ && "$(docker context show)" == colima ]]
sdk="${MAC_DEMO_SDK_ROOT:-$repo/.work/fresh-fullflow-20261021/sdk019/deployed-install}"
if [[ -d "$sdk/opentradingcore" ]]; then
  export PYTHONPATH="$sdk${PYTHONPATH:+:$PYTHONPATH}"
fi
python3 -c 'from opentradingcore import OpenTradingCoreClient'
for service in gateway mysql; do
  [[ "$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' "dc-saas-$service")" == "$generation" ]]
done

for kind in order trade; do
  for slot in a b; do
    [[ "$(docker inspect -f '{{.State.Running}}' "$generation-$kind-$slot-hostready")" == true ]]
  done
done
port="$(sed -n 's/^GW_HTTP_PORT=\([0-9][0-9]*\)$/\1/p' "$run_dir/demo.env")"
[[ "$port" =~ ^[0-9]+$ && "$port" -gt 0 && "$port" -le 65535 ]]
ssh_config="${COLIMA_SSH_CONFIG:-${HOME}/.colima/_lima/colima/ssh.config}"
ssh_host="${COLIMA_SSH_HOST:-lima-colima}"
tunnel="$(mktemp -d /tmp/otc-demo-ssh.XXXXXX)"
cleanup() {
  ssh -F "$ssh_config" -S "$tunnel/control" -O exit "$ssh_host" >/dev/null 2>&1 || true
  rmdir "$tunnel" 2>/dev/null || true
}
trap cleanup EXIT
# Colima may already forward the Gateway port. Use a short-lived local
# port of our own and target the exact reviewed Gateway inside this VM.
forward_port="$(python3 - <<'PY'
import socket
with socket.socket() as probe:
    probe.bind(('127.0.0.1', 0))
    print(probe.getsockname()[1])
PY
)"
ssh -F "$ssh_config" -M -S "$tunnel/control" -o ConnectTimeout=8 -o ExitOnForwardFailure=yes \
  -fN -L "127.0.0.1:$forward_port:127.0.0.1:$port" "$ssh_host"
endpoint="http://127.0.0.1:$forward_port/httpapi/"
python3 - "$endpoint" <<'PY'
import json
import sys
import time
import urllib.request

probes = [
    ("ManagerSvr", "tenantApplication", {
        "action": "STATUS",
        "application_id": "mac-demo-readiness-probe",
        "contact_email": "readiness@acceptance.invalid",
    }, 9004, "tenant application was not found"),
    ("LoginSvr", "SYS.ATS.LOGIN", {
        "method": "login",
        "cid": "MAC_DEMO_READINESS",
        "user_id": "macdemo-readiness-probe",
        "user_name": "macdemo-readiness-probe",
        "password": "demo-readiness-probe-unused",
        "client_type": "TenantAdmin",
        "Location": "READINESS",
    }, 9005, "user_account_or_pwd_error"),
]
client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
deadline = time.monotonic() + 240
for service, method, content, code, message in probes:
    query = {"serverName": service, "method": method, "content": content}
    request = urllib.request.Request(sys.argv[1], json.dumps(query).encode(),
                                     {"Content-Type": "application/json"})
    while time.monotonic() < deadline:
        try:
            with client.open(request, timeout=4) as response:
                result = json.load(response)
            # Deliberately absent application and user. The expected service
            # responses prove routing without opening a session or a tenant.
            if (isinstance(result, dict) and result.get("code") == code
                    and message in str(result.get("msg", "")).lower()):
                break
        except (OSError, ValueError):
            pass
        time.sleep(2)
    else:
        sys.exit(f"Gateway could not route the readiness probe to {service}")
PY

export OTC_E2E_MYSQL_CONTAINER=dc-saas-mysql
results="$(mktemp -d "$run_dir/verification.XXXXXX")"
printf '[mac-demo] Business logs: %s\n' "$results"
if [[ -n "$ha_evidence" ]]; then
  export PYTHONUNBUFFERED=1
  if [[ "$ha_mode" == funded ]]; then
    python3 "$repo/tests/test-custom-product-live-e2e.py" --execute --with-traders --sdk-signed \
      --endpoint "$endpoint" --ha-evidence-dir "$ha_evidence" --ha-timeout "$ha_timeout"
  else
    python3 "$repo/tests/test-order-only-product-live-e2e.py" --execute \
      --endpoint "$endpoint" --ha-evidence-dir "$ha_evidence" --ha-timeout "$ha_timeout"
  fi
  exit
fi
status=0
python3 "$repo/tests/test-order-only-product-live-e2e.py" --execute --endpoint "$endpoint" \
  | tee "$results/order-only-e2e.log" || status=1
python3 "$repo/tests/test-custom-product-live-e2e.py" --execute --with-traders --sdk-signed --endpoint "$endpoint" \
  | tee "$results/trade-e2e.log" || status=1
if [[ "$status" != 0 ]]; then
  # Capture the failed JVM before automatic rollback retires it. A bounded
  # read-only thread dump distinguishes incomplete startup from stale prices.
  python3 - "$generation" "$results" <<'PY'
import json
import os
from pathlib import Path
import subprocess
import sys

os.umask(0o077)
generation, output = sys.argv[1], Path(sys.argv[2])
try:
    inspected = subprocess.run(['docker', 'inspect', 'dc-saas-mdsvr'],
                               capture_output=True, text=True, check=True, timeout=10)
    container = json.loads(inspected.stdout)[0]
    if (container['Config']['Labels'].get('com.docker.compose.project') != generation
            or not container['State']['Running']):
        raise RuntimeError('Failed generation MD is no longer running')
    listed = subprocess.run(['docker', 'exec', container['Id'], 'jcmd', '-l'],
                            capture_output=True, text=True, check=True, timeout=10)
    processes = [line.split()[0] for line in listed.stdout.splitlines()
                 if len(line.split()) > 1 and line.split()[1] == 'MDSvr']
    if len(processes) != 1 or not processes[0].isdigit():
        raise RuntimeError('Expected one actual MDSvr JVM')
    dump = subprocess.run(['docker', 'exec', container['Id'], 'jcmd', processes[0], 'Thread.print'],
                          capture_output=True, text=True, check=True, timeout=15)
    (output / 'failed-md-threads.txt').write_text(dump.stdout)
    print('[mac-demo] Failed MD thread evidence saved in ' + str(output))
except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
    print('[mac-demo] Failed MD thread capture unavailable (' + type(error).__name__ + ')')
PY
  exit "$status"
fi

printf '[mac-demo] Matching each customer execution to its unique public trade.\n'
python3 - "$repo" "$endpoint" "$results" <<'PY' | tee "$results/public-execution-matches.json"
import json
from pathlib import Path
import re
import runpy
import sys

repo, endpoint, output = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
helpers = runpy.run_path(str(repo / "tests/test-custom-product-live-e2e.py"))
verified = {}
for mode, key, event in (("order-only", "checkpoint", "tenant_created"),
                         ("trade", "step", "tenant_approved")):
    log = output / f"{mode}-e2e.log"
    rows = [json.loads(line) for line in log.read_text().splitlines() if line.startswith("{")]
    locations = [row.get("location") for row in rows if row.get(key) == event]
    if len(locations) != 1 or not re.fullmatch(r"[A-Z0-9]{6}", locations[0] or ""):
        raise RuntimeError(f"Expected one actual test tenant for {mode}")
    location = locations[0]
    executions = helpers["readonly_sql"](
        "SELECT exec_id FROM dc_orders_execorders "
        f"WHERE location='{location}' AND security_id='BTC003USDT' AND last_qty>0 ORDER BY exec_id")
    exec_ids = {row[0] for row in executions}
    public_id = helpers["verify_ha_market"](endpoint, location)
    if len(executions) != 2 or len(exec_ids) != 2 or public_id not in exec_ids:
        raise RuntimeError(f"Public trade does not match the certified customer execution for {mode}")
    verified[mode] = {"tenant": location, "execution_ids": sorted(exec_ids), "public_trade_id": public_id}
print(json.dumps(verified, sort_keys=True))
PY

printf '[mac-demo] Waiting for a trial tenant to quote and execute a real Tape order.\n'
deadline=$((SECONDS + 180))
while :; do
  if python3 "$repo/tests/check_trial_robot_trade_e2_readonly.py" --mysql dc-saas-mysql \
       --order-a "$generation-order-a-hostready" --order-b "$generation-order-b-hostready" \
       --minutes 10 --min-locations 1 > "$results/robot-tape-e2e.json"; then
    cat "$results/robot-tape-e2e.json"
    break
  fi
  if (( SECONDS >= deadline )); then
    cat "$results/robot-tape-e2e.json"
    exit 2
  fi
  sleep 5
done

printf '[mac-demo] Reconciling the certified Trade cursor, balances and positions.\n'
deadline=$((SECONDS + 90))
while :; do
  if python3 "$repo/tests/check_certified_trade_financial_cursor.py" --mysql dc-saas-mysql --min-epoch 2 \
       > "$results/trade-financial-cursor.json"; then
    cat "$results/trade-financial-cursor.json"
    break
  fi
  if (( SECONDS >= deadline )); then
    cat "$results/trade-financial-cursor.json"
    exit 2
  fi
  sleep 3
done
