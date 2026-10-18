#!/usr/bin/env bash
# Non-destructive regression test: mock Docker; NEVER touch the real database.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf -- "$TMP"' EXIT
mkdir -p "$TMP/bin"
cat > "$TMP/bin/docker" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-} ${2:-}" in
  'inspect dc-saas-mysql') printf 'running\n' ;;
  'inspect dc-saas-loginsvr') : ;;
  'restart dc-saas-loginsvr') printf 'loginsvr_restart\n' >> "$MOCK_DOCKER_CALLS" ;;
  'exec -i') cat >/dev/null; printf 'identity_write\n' >> "$MOCK_DOCKER_CALLS" ;;
  'exec -e') printf '0\n'; printf 'robot_key_lookup\n' >> "$MOCK_DOCKER_CALLS" ;;
  *) echo 'unexpected Docker invocation' >&2; exit 22 ;;
esac
MOCK
chmod +x "$TMP/bin/docker"
cat > "$TMP/test.env" <<'ENV'
PLATFORM_ADMIN_USERNAME=testplatform
PLATFORM_ADMIN_PASSWORD=dummy-only-do-not-use
ROBOT_RUNTIME_LOCATION=PLATFORM
ROBOT_RUNTIME_USER_ID=robotsvrtest
ROBOT_RUNTIME_API_KEY=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
ROBOT_RUNTIME_API_SECRET=BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB
MYSQL_ROOT_PASSWORD=dummy-test-only
MYSQL_PORT=3306
ENV
chmod 600 "$TMP/test.env"
export MOCK_DOCKER_CALLS="$TMP/calls"
SAAS_ALLOW_UNPRIVILEGED_HOST=true SAAS_DEPLOY_LOCK_HELD=true PATH="$TMP/bin:$PATH" ENV_FILE="$TMP/test.env" bash "$SCRIPT_DIR/deploy-saas.sh" --provision-identities-only > "$TMP/stdout"
test "$(grep -c '^identity_write$' "$TMP/calls")" = 2
test "$(grep -c '^robot_key_lookup$' "$TMP/calls")" = 1
test "$(grep -c '^loginsvr_restart$' "$TMP/calls")" = 1
if grep -Ei '(pulling|building|starting.*SaaS services|database migration)' "$TMP/stdout"; then
  echo 'Identity-only path attempted a full redeploy' >&2; exit 1
fi
if SAAS_ALLOW_UNPRIVILEGED_HOST=true SAAS_DEPLOY_LOCK_HELD=true ENV_FILE="$TMP/missing.env" bash "$SCRIPT_DIR/deploy-saas.sh" --provision-identities-only > "$TMP/missing.log" 2>&1; then
  echo 'Missing private environment should fail closed' >&2; exit 1
fi
grep -q 'Existing private ENV_FILE is required' "$TMP/missing.log"
echo 'PASS: identity-only mode uses official provisioning, reloads LoginSvr only, rejects missing env.'
