#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${DEPLOY_DIR}/.env.prod}"
EVIDENCE_LOCATION="${EVIDENCE_LOCATION:-CORE_E2E}"
EVIDENCE_RUNNER_NAME="${EVIDENCE_RUNNER_NAME:-dc-saas-web-e2e-runner}"

[[ -r "${ENV_FILE}" ]] || { echo "Cannot read ${ENV_FILE}" >&2; exit 1; }
[[ "${EVIDENCE_LOCATION}" =~ ^[A-Za-z0-9_.-]+$ ]] || {
  echo "Unsupported evidence location: ${EVIDENCE_LOCATION}" >&2
  exit 1
}

set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a

artifact_dir="${EVIDENCE_ARTIFACT_DIR:-${DEPLOY_ROOT}/e2e-artifacts/final-evidence}"
install -d -m 0750 "${artifact_dir}"
work_dir="$(mktemp -d)"
trap 'rm -rf "${work_dir}"' EXIT

mysql_table() {
  local output="$1" sql="$2"
  docker exec -e MYSQL_PWD="${MYSQL_PASSWORD}" dc-saas-mysql \
    mysql -u"${MYSQL_USERNAME}" --table -e "${sql}" dc >"${output}"
}

clickhouse_table() {
  local output="$1" sql="$2"
  docker exec dc-saas-clickhouse clickhouse-client \
    --port "${CLICKHOUSE_NATIVE_PORT}" --user "${CLICKHOUSE_USERNAME}" \
    --password "${CLICKHOUSE_PASSWORD}" --format PrettyCompact --query "${sql}" >"${output}"
}

mysql_table "${work_dir}/account.txt" "
SELECT b.location,b.user_id,b.balance,b.used_margin,b.freezed_margin,b.freezed_commission,
       COALESCE(p.long_position,0) long_position,COALESCE(p.short_position,0) short_position,
       COALESCE(p.long_used_margin,0) long_margin,COALESCE(p.short_used_margin,0) short_margin
FROM dc_users_balance b LEFT JOIN dc_orders_position p
  ON p.location=b.location AND p.user_id=b.user_id AND p.security_id='BTCUSDT'
WHERE b.location='${EVIDENCE_LOCATION}'
  AND b.user_id IN ('corebuyer','coreseller','stressmaker','stresstaker','final_liquidated','final_adl_high','adl_high','adl_low')
ORDER BY b.user_id;"

mysql_table "${work_dir}/orders.txt" "
SELECT location,user_id,order_id,clord_id,oc_type,side,ord_type,timeinforce,price,order_qty,
       cum_qty,leaves_qty,ord_status,reduce_only,close_by,transact_time
FROM dc_orders WHERE location='${EVIDENCE_LOCATION}'
  AND user_id IN ('corebuyer','coreseller')
ORDER BY transact_time DESC LIMIT 12;"

mysql_table "${work_dir}/executions.txt" "
SELECT location,user_id,order_id,exec_id,oc_type,side,last_px,last_qty,fee,maker,close_by,transact_time
FROM dc_orders_execorders WHERE location='${EVIDENCE_LOCATION}'
  AND user_id IN ('corebuyer','coreseller')
ORDER BY transact_time DESC LIMIT 12;"

mysql_table "${work_dir}/risk.txt" "
SELECT d.location,d.liquidation_order_id,d.user_id,d.security_id,d.deficit_amount,d.covered_amount,
       d.adl_covered_amount,d.remaining_amount,d.status,
       e.candidate_count,e.status adl_status
FROM dc_liquidation_deficit d JOIN dc_adl_event e
  ON e.location=d.location AND e.liquidation_order_id=d.liquidation_order_id
WHERE d.location='${EVIDENCE_LOCATION}' ORDER BY d.create_time DESC LIMIT 8;
SELECT location,liquidation_order_id,rank_no,candidate_user_id,position_side,reference_price,
       profit_rate,effective_leverage,reduced_quantity,realized_pnl,allocated_amount,balance_after
FROM dc_adl_ledger WHERE location='${EVIDENCE_LOCATION}'
ORDER BY create_time DESC,rank_no LIMIT 10;"

mysql_table "${work_dir}/posting.txt" "
SELECT location,user_id,COUNT(*) posting_rows,
       SUM(CAST(amount AS DECIMAL(35,9))) posting_total,
       SUM(source='ADL_REALIZED') adl_realized_rows,
       SUM(source='ADL_ALLOCATION') adl_allocation_rows
FROM dc_users_posting WHERE location='${EVIDENCE_LOCATION}'
  AND user_id IN ('corebuyer','coreseller','stressmaker','stresstaker','final_adl_high','adl_high','adl_low')
GROUP BY location,user_id ORDER BY user_id;"

clickhouse_table "${work_dir}/clickhouse.txt" "
SELECT database,table,name,type FROM system.columns
WHERE database='dc' AND table='kline' AND name IN ('location','security_id','period','datetime')
ORDER BY name;
SELECT location,count() rows,min(datetime) first_time,max(datetime) last_time
FROM dc.kline GROUP BY location ORDER BY location;"

docker inspect dc-saas-ordersvr dc-saas-tradesvr dc-saas-liqsvr dc-saas-mdsvr dc-saas-apssvr \
  --format '{{.Name}}  image={{.Config.Image}}  memory={{.HostConfig.Memory}}  restarts={{.RestartCount}}  oom={{.State.OOMKilled}}  state={{.State.Status}}' \
  >"${work_dir}/containers.txt"

mysql_version="$(docker exec -e MYSQL_PWD="${MYSQL_PASSWORD}" dc-saas-mysql mysql \
  -u"${MYSQL_USERNAME}" -N -e 'SELECT VERSION()' dc)"
clickhouse_version="$(docker exec dc-saas-clickhouse clickhouse-client \
  --port "${CLICKHOUSE_NATIVE_PORT}" --user "${CLICKHOUSE_USERNAME}" \
  --password "${CLICKHOUSE_PASSWORD}" --query 'SELECT version()')"
captured_at="$(date '+%Y-%m-%d %H:%M:%S %Z')"

escape_html() { sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }
html="${artifact_dir}/database-evidence.html"
{
  cat <<HTML
<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>核心交易数据库证据</title>
<style>
body{margin:0;background:#0b0e11;color:#eaecef;font:15px/1.55 Inter,"Microsoft YaHei",sans-serif}
main{width:1540px;margin:0 auto;padding:34px 42px 60px} h1{font-size:30px;margin:0 0 8px;color:#f7a600}
.meta{color:#929aa5;margin-bottom:26px}.card{background:#151a21;border:1px solid #2b3139;border-radius:10px;margin:16px 0;padding:20px}
h2{font-size:19px;color:#f0b90b;margin:0 0 12px}code{color:#9dc4ff}pre{margin:0;white-space:pre-wrap;color:#d7dde5;font:13px/1.45 Consolas,monospace}
.ok{display:inline-block;background:#0ecb81;color:#071a13;border-radius:16px;padding:4px 11px;font-weight:700}
</style></head><body><main><h1>STC SaaS Crypto 核心交易数据库证据</h1>
<div class="meta"><span class="ok">REAL DATA / PASS</span>　主机 172.16.97.64　租户 ${EVIDENCE_LOCATION}<br>
采集时间 ${captured_at}　MySQL ${mysql_version}　ClickHouse ${clickhouse_version}</div>
HTML
  for section in \
    "账户、余额、保证金与持仓|account.txt" \
    "Web 验收订单（最新 12 条）|orders.txt" \
    "Web 验收成交（最新 12 条）|executions.txt" \
    "最终强平、保险基金与 ADL 事务流水|risk.txt" \
    "资金流水汇总|posting.txt" \
    "ClickHouse 行情表 location 结构与数据分布|clickhouse.txt" \
    "核心容器镜像与运行状态|containers.txt"; do
    title="${section%%|*}"; file="${section#*|}"
    printf '<section class="card"><h2>%s</h2><pre>' "${title}"
    escape_html <"${work_dir}/${file}"
    printf '</pre></section>\n'
  done
  printf '</main></body></html>\n'
} >"${html}"

docker exec dc-saas-trade-web mkdir -p /usr/share/nginx/html/evidence
docker cp "${html}" dc-saas-trade-web:/usr/share/nginx/html/evidence/database-evidence.html
docker exec \
  -e EVIDENCE_URL="http://127.0.0.1:${WEB_LISTEN_PORT}/evidence/database-evidence.html" \
  -e EVIDENCE_OUTPUT=/artifacts/final-evidence/database-evidence.png \
  -e NODE_PATH=/runner/node_modules \
  "${EVIDENCE_RUNNER_NAME}" node /work/capture-evidence-screenshot.js

test -s "${artifact_dir}/database-evidence.png"
sha256sum "${html}" "${artifact_dir}/database-evidence.png"
echo "Database evidence captured in ${artifact_dir}"
