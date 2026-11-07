#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${SCRIPT_DIR}/mac-colima-saas.sh"

fail() { printf '[test-mac-colima-saas] ERROR: %s\n' "$*" >&2; exit 1; }

/bin/bash -n "${TARGET}" || fail "mac-colima-saas.sh has invalid bash syntax"
for port in 18088 18090 18092; do
  grep -Fq "${port}" "${TARGET}" || fail "missing Web forward port ${port}"
done
grep -Fq 'install-saas.sh' "${TARGET}" || fail "wrapper must delegate install to install-saas.sh"
grep -Fq 'uninstall-saas.sh' "${TARGET}" || fail "wrapper must delegate uninstall to uninstall-saas.sh"
grep -Fq 'acceptance-saas.sh' "${TARGET}" || fail "wrapper must delegate acceptance to acceptance-saas.sh"
grep -Fq '.default-e2e-credentials.txt' "${TARGET}" || fail "wrapper must surface default E2E credentials"
if grep -Eq 'pkill|killall|open -a v2ray|docker restart' "${TARGET}"; then
  fail "Mac wrapper must not manage v2ray/xray or restart Docker"
fi
# Mac one-click must reject mixed Common JARs before touching containers.
/bin/bash "${SCRIPT_DIR}/tests/test-deploy-common-image-parity.sh"
# The one-click deploy must seed a dedicated Robot Gateway user and Runtime key.
python3 -m unittest discover -s "${SCRIPT_DIR}/tests" -p test_provision_robot_service_user.py -q
# Fresh Trial Worker/Robot/APS must be checked against live runtime, not merely Compose YAML.
python3 -m unittest discover -s "${SCRIPT_DIR}/tests" -p test_trial_robot_live_readiness.py -q
# Opt-in Binance SOCKS5 proxy is scoped to APS and does not proxy internal cluster.
python3 -m unittest discover -s "${SCRIPT_DIR}/tests" -p test_apssvr_binance_socks_wiring.py -q
# Business E2E: must prove real Tape Filled IDs and certified Trade posting pairs.
# Unit contract checks run offline; the live gate is invoked with real containers.
python3 -m unittest discover -s "${SCRIPT_DIR}/tests" -p test_trial_robot_trade_e2_readonly.py -q
# T542: no false K-line PASS from blank, duplicate or invalid OHLC history.
python3 -m unittest discover -s "${SCRIPT_DIR}/tests" -p test_demo_full_market_readonly.py -q
# T543: prevent heavy internal system ClickHouse MergeTree logs from OOM K-line.
python3 -m unittest discover -s "${SCRIPT_DIR}/tests" -p test_clickhouse_internal_logs_profile.py -q
# T543: verify latest K-line/default-live-market Web source on one-click.
python3 -m unittest discover -s "${SCRIPT_DIR}/tests" -p test_trade_web_active_market_source.py -q
# T543: enforce same dynamic Gateway port in public/tenant/platform/trade Web.
python3 -m unittest discover -s "${SCRIPT_DIR}/tests" -p test_frontend_gateway_templates.py -q
# T546: offline guard contract. The separate live rolling preflight must
 # check physically pinned Common, poison status and automatic recovery.
python3 -m unittest discover -s "${SCRIPT_DIR}/tests" -p test_order_live_rollout_preflight.py -q
printf '[test-mac-colima-saas] PASS\n'
