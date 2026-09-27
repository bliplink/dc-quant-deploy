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
printf '[test-mac-colima-saas] PASS\n'
