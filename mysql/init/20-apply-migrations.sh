#!/bin/bash
# MySQL's initdb.d runs this after 00/10/11/12/13 *.sql files, while the
# temporary fresh-install server is still accepting only local sockets.
# Never let healthy MySQL (or any upstream service) start with a partial schema.
set -Eeuo pipefail
shopt -s nullglob
files=(/opt/saas-migrations/*.sql)
if (( ${#files[@]} < 20 )); then
  echo '[fresh-mysql] missing bundled versioned migrations; fail closed' >&2
  exit 1
fi
for file in "${files[@]}"; do
  printf '[fresh-mysql] migration %s\n' "${file##*/}"
  MYSQL_PWD="${MYSQL_ROOT_PASSWORD:?}" mysql --protocol=socket -uroot dc < "$file"
done
# Assert business-critical tables before boot completes (cold-start services
# such as Trade ADL and Admin trial bootstrap must not query absent tables).
actual=$(MYSQL_PWD="${MYSQL_ROOT_PASSWORD:?}" mysql --protocol=socket -uroot -N -e \
  "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='dc' AND table_name IN ('dc_tenant','dc_bankruptcy_transfer','dc_adl_execution_v2','dc_tenant_liquidity_bootstrap')")
if [[ "$actual" != '4' ]]; then
  echo "[fresh-mysql] missing mandatory business tables: found ${actual}/4" >&2
  exit 1
fi
# Stamp completion ONLY after every versioned migration succeeded. Readers can
# distinguish completed initialization from a server restarted after SQL error.
MYSQL_PWD="${MYSQL_ROOT_PASSWORD:?}" mysql --protocol=socket -uroot dc <<'SQL'
CREATE TABLE IF NOT EXISTS dc_fresh_schema_install_status (
  marker varchar(24) NOT NULL PRIMARY KEY,
  ready tinyint(1) NOT NULL,
  updated_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;
INSERT INTO dc_fresh_schema_install_status(marker,ready)
VALUES ('all-migrations-done',1)
ON DUPLICATE KEY UPDATE ready=VALUES(ready),updated_at=CURRENT_TIMESTAMP;
SQL
echo '[fresh-mysql] schema bootstrap complete, all mandatory tables present'
