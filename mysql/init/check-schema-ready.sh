#!/bin/sh
# Read-only health probe. Fresh installs have an initializing marker (ready=0)
# until all SQL scripts and versioned migrations complete. Databases provisioned
# by earlier releases lack this marker: retain their original critical-table
# health check for a non-destructive upgrade.
set -eu
export MYSQL_PWD="${MYSQL_ROOT_PASSWORD:?}"
mysql_cmd() {
  mysql --protocol=TCP -h127.0.0.1 -P"${MYSQL_TCP_PORT:-33306}" -uroot -N -e "$1"
}
marker=$(mysql_cmd "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='dc' AND table_name='dc_fresh_schema_install_status'" 2>/dev/null) || exit 1
if [ "$marker" = 1 ]; then
  state=$(mysql_cmd "SELECT ready FROM dc.dc_fresh_schema_install_status WHERE marker='all-migrations-done'" 2>/dev/null) || exit 1
  [ "$state" = 1 ] || exit 1
fi
critical=$(mysql_cmd "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='dc' AND table_name IN ('dc_tenant','dc_bankruptcy_transfer','dc_adl_execution_v2','dc_tenant_liquidity_bootstrap')" 2>/dev/null) || exit 1
[ "$critical" = 4 ]
