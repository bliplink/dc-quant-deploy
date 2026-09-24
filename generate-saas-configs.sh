#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${1:-${SCRIPT_DIR}/.env.prod}"

log() {
  printf '[saas-config] %s\n' "$*"
}

die() {
  printf '[saas-config] ERROR: %s\n' "$*" >&2
  exit 1
}

[[ -r "${ENV_FILE}" ]] || die "Cannot read ${ENV_FILE}"

set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a

required_vars=(
  DEPLOY_ROOT
  MYSQL_PORT MYSQL_USERNAME MYSQL_PASSWORD
  CLICKHOUSE_HTTP_PORT CLICKHOUSE_USERNAME CLICKHOUSE_PASSWORD
  ZOOKEEPER_PORT
  GW_TCP_PORT GW_WEBSOCKET_PORT GW_HTTP_PORT
  LOGINSVR_HTTP_PORT LOGINSVR_GW_PORT
  MDSVR_GW_PORT APSSVR_GW_PORT ORDERSVR_GW_PORT TRADESVR_GW_PORT
  LIQSVR_GW_PORT MANAGERSVR_GW_PORT ADMINSVR_GW_PORT
  APSSVR_BINANCE_REST_URL APSSVR_BINANCE_WS_URL
  APSSVR_SYMBOLS APSSVR_SYMBOL_ALIASES APSSVR_ENABLE_USER_DATA
  LOGIN_DEFAULT_PASSWORD
)

for name in "${required_vars[@]}"; do
  [[ -n "${!name:-}" ]] || die "Missing required variable: ${name}"
done

ORDER_CLUSTER_ENABLED="${ORDER_CLUSTER_ENABLED:-false}"
ORDER_CLUSTER_C_ENABLED="${ORDER_CLUSTER_C_ENABLED:-false}"
MD_CLUSTER_ENABLED="${MD_CLUSTER_ENABLED:-false}"
MD_CLUSTER_C_ENABLED="${MD_CLUSTER_C_ENABLED:-false}"
TRADE_CLUSTER_ENABLED="${TRADE_CLUSTER_ENABLED:-false}"
PROTO_VERSION=1
ORDER_CLUSTER_REPLICATION_CONSISTENCY_MODE="${ORDER_CLUSTER_REPLICATION_CONSISTENCY_MODE:-SYNC_PER_RECORD}"
ORDER_CLUSTER_REPLICATION_BATCH_MAX_RECORDS="${ORDER_CLUSTER_REPLICATION_BATCH_MAX_RECORDS:-64}"
ORDER_CLUSTER_REPLICATION_BATCH_MAX_WAIT_MICROS="${ORDER_CLUSTER_REPLICATION_BATCH_MAX_WAIT_MICROS:-1000}"
ORDER_CLUSTER_REPLICATION_BATCH_THREADS="${ORDER_CLUSTER_REPLICATION_BATCH_THREADS:-2}"
ORDER_CLUSTER_REPLICATION_ASYNC_RETRY_MILLIS="${ORDER_CLUSTER_REPLICATION_ASYNC_RETRY_MILLIS:-100}"
ORDER_CLUSTER_REPLICATION_ASYNC_MAX_PENDING_RECORDS="${ORDER_CLUSTER_REPLICATION_ASYNC_MAX_PENDING_RECORDS:-8192}"
# Snapshot chunks currently share the Order journal. Keep periodic capture
# opt-in until snapshot transfer has its own bounded transport/retention path;
# otherwise a large idempotency snapshot amplifies every partition journal.
ORDER_CLUSTER_PERIODIC_SNAPSHOT_ENABLED="${ORDER_CLUSTER_PERIODIC_SNAPSHOT_ENABLED:-false}"
ORDER_CLUSTER_PERIODIC_SNAPSHOT_POLL_MILLIS="${ORDER_CLUSTER_PERIODIC_SNAPSHOT_POLL_MILLIS:-5000}"
ORDER_CLUSTER_PERIODIC_SNAPSHOT_MAX_AGE_MILLIS="${ORDER_CLUSTER_PERIODIC_SNAPSHOT_MAX_AGE_MILLIS:-300000}"
ORDER_CLUSTER_PERIODIC_SNAPSHOT_MIN_COMMITTED_MUTATIONS="${ORDER_CLUSTER_PERIODIC_SNAPSHOT_MIN_COMMITTED_MUTATIONS:-10000}"
ORDER_CLUSTER_PERIODIC_SNAPSHOT_MAX_PARTITIONS_PER_RUN="${ORDER_CLUSTER_PERIODIC_SNAPSHOT_MAX_PARTITIONS_PER_RUN:-4}"
PROJECTIONSVR_GW_PORT="${PROJECTIONSVR_GW_PORT:-33042}"
if [[ "${ORDER_CLUSTER_ENABLED}" == "true" || "${MD_CLUSTER_ENABLED}" == "true" || "${TRADE_CLUSTER_ENABLED}" == "true" ]]; then
  PROTO_VERSION=2
fi
if [[ "${ORDER_CLUSTER_ENABLED}" == "true" ]]; then
  for name in ORDERSVR_B_GW_PORT ORDERSVR_A_REPLICATION_PORT ORDERSVR_B_REPLICATION_PORT; do
    [[ -n "${!name:-}" ]] || die "Missing required cluster variable: ${name}"
  done
  case "${ORDER_CLUSTER_REPLICATION_CONSISTENCY_MODE}" in
    SYNC_PER_RECORD|SYNC_BATCHED|ASYNC_BATCHED) ;;
    *) die "ORDER_CLUSTER_REPLICATION_CONSISTENCY_MODE must be SYNC_PER_RECORD, SYNC_BATCHED or ASYNC_BATCHED" ;;
  esac
  [[ "${ORDER_CLUSTER_REPLICATION_BATCH_MAX_RECORDS}" =~ ^[1-9][0-9]*$ ]] ||
    die "ORDER_CLUSTER_REPLICATION_BATCH_MAX_RECORDS must be a positive integer"
  [[ "${ORDER_CLUSTER_REPLICATION_BATCH_MAX_WAIT_MICROS}" =~ ^[0-9]+$ ]] ||
    die "ORDER_CLUSTER_REPLICATION_BATCH_MAX_WAIT_MICROS must be a non-negative integer"
  [[ "${ORDER_CLUSTER_REPLICATION_BATCH_THREADS}" =~ ^[1-9][0-9]*$ ]] ||
    die "ORDER_CLUSTER_REPLICATION_BATCH_THREADS must be a positive integer"
  [[ "${ORDER_CLUSTER_REPLICATION_ASYNC_RETRY_MILLIS}" =~ ^[1-9][0-9]*$ ]] ||
    die "ORDER_CLUSTER_REPLICATION_ASYNC_RETRY_MILLIS must be a positive integer"
  [[ "${ORDER_CLUSTER_REPLICATION_ASYNC_MAX_PENDING_RECORDS}" =~ ^[1-9][0-9]*$ ]] ||
    die "ORDER_CLUSTER_REPLICATION_ASYNC_MAX_PENDING_RECORDS must be a positive integer"
  [[ "${ORDER_CLUSTER_PERIODIC_SNAPSHOT_ENABLED}" == "true" || "${ORDER_CLUSTER_PERIODIC_SNAPSHOT_ENABLED}" == "false" ]] ||
    die "ORDER_CLUSTER_PERIODIC_SNAPSHOT_ENABLED must be true or false"
  for name in ORDER_CLUSTER_PERIODIC_SNAPSHOT_POLL_MILLIS ORDER_CLUSTER_PERIODIC_SNAPSHOT_MAX_AGE_MILLIS \
      ORDER_CLUSTER_PERIODIC_SNAPSHOT_MIN_COMMITTED_MUTATIONS ORDER_CLUSTER_PERIODIC_SNAPSHOT_MAX_PARTITIONS_PER_RUN; do
    [[ "${!name}" =~ ^[1-9][0-9]*$ ]] || die "${name} must be a positive integer"
  done
fi
if [[ "${ORDER_CLUSTER_C_ENABLED}" == "true" ]]; then
  [[ "${ORDER_CLUSTER_ENABLED}" == "true" ]] || die "ORDER_CLUSTER_C_ENABLED requires ORDER_CLUSTER_ENABLED=true"
  for name in ORDERSVR_C_GW_PORT ORDERSVR_C_REPLICATION_PORT; do
    [[ -n "${!name:-}" ]] || die "Missing required OrderSvrC variable: ${name}"
  done
fi
if [[ "${MD_CLUSTER_ENABLED}" == "true" ]]; then
  [[ -n "${MDSVR_B_GW_PORT:-}" ]] || die "Missing required cluster variable: MDSVR_B_GW_PORT"
fi
if [[ "${MD_CLUSTER_C_ENABLED}" == "true" ]]; then
  [[ "${MD_CLUSTER_ENABLED}" == "true" ]] || die "MD_CLUSTER_C_ENABLED requires MD_CLUSTER_ENABLED=true"
  [[ -n "${MDSVR_C_GW_PORT:-}" ]] || die "Missing required MDSvrC variable: MDSVR_C_GW_PORT"
fi
if [[ "${TRADE_CLUSTER_ENABLED}" == "true" ]]; then
  for name in TRADESVR_B_GW_PORT TRADESVR_A_REPLICATION_PORT TRADESVR_B_REPLICATION_PORT; do
    [[ -n "${!name:-}" ]] || die "Missing required Trade cluster variable: ${name}"
  done
fi

CONTROL_ROOT="${DEPLOY_ROOT}/control"
OVERRIDE_ROOT="${CONTROL_ROOT}/overrides"
umask 077

install -d -m 0750 "${CONTROL_ROOT}" "${OVERRIDE_ROOT}/GW/config" "${OVERRIDE_ROOT}/LoginSvr/config" "${OVERRIDE_ROOT}/MDSvr/config" "${OVERRIDE_ROOT}/MDSvrA/config" "${OVERRIDE_ROOT}/MDSvrB/config" "${OVERRIDE_ROOT}/MDSvrC/config" "${OVERRIDE_ROOT}/APSSvr/config" "${OVERRIDE_ROOT}/OrderSvr/config" "${OVERRIDE_ROOT}/OrderSvrA/config" "${OVERRIDE_ROOT}/OrderSvrB/config" "${OVERRIDE_ROOT}/OrderSvrC/config" "${OVERRIDE_ROOT}/ProjectionSvr/config" "${OVERRIDE_ROOT}/TradeSvr/config" "${OVERRIDE_ROOT}/TradeSvrA/config" "${OVERRIDE_ROOT}/TradeSvrB/config" "${OVERRIDE_ROOT}/LiqSvr/config" "${OVERRIDE_ROOT}/ManagerSvr/config" "${OVERRIDE_ROOT}/AdminSvr/config"

cat > "${CONTROL_ROOT}/DBPoolConfig.ini" <<EOF
[DBPOOL]
DBPOOL.DBCount=2
DBPOOL.LogLevel=0
DBPOOL.LogPath=../../log/DBPool.log

DBPOOL.DBSourceName_0=MYSQL0
DBPOOL.DBDriver_0=com.mysql.cj.jdbc.Driver
DBPOOL.DBUrl_0=jdbc:mysql://127.0.0.1:${MYSQL_PORT}/dc?useSSL=false&allowPublicKeyRetrieval=true&serverTimezone=Asia/Shanghai&characterEncoding=UTF-8
DBPOOL.DBUsername_0=${MYSQL_USERNAME}
DBPOOL.DBPasswd_0=${MYSQL_PASSWORD}
DBPOOL.DBCheckSql_0=select 1
DBPOOL.DBIsEncrypt_0=false
DBPOOL.DBMaxCount_0=30
DBPOOL.DBMinCount_0=2
DBPOOL.DBConnOutTime_0=3000
DBPOOL.DBConnCheckNumber_0=60
DBPOOL.DBStrategy_0=false

DBPOOL.DBSourceName_1=MYSQL1
DBPOOL.DBDriver_1=com.mysql.cj.jdbc.Driver
DBPOOL.DBUrl_1=jdbc:mysql://127.0.0.1:${MYSQL_PORT}/event?useSSL=false&allowPublicKeyRetrieval=true&serverTimezone=Asia/Shanghai&characterEncoding=UTF-8
DBPOOL.DBUsername_1=${MYSQL_USERNAME}
DBPOOL.DBPasswd_1=${MYSQL_PASSWORD}
DBPOOL.DBCheckSql_1=select 1
DBPOOL.DBIsEncrypt_1=false
DBPOOL.DBMaxCount_1=10
DBPOOL.DBMinCount_1=1
DBPOOL.DBConnOutTime_1=3000
DBPOOL.DBConnCheckNumber_1=60
DBPOOL.DBStrategy_1=false

CLICKHOUSE.DBCount=1
CLICKHOUSE.DBSourceName_0=ClickHouse1
CLICKHOUSE.DBUrl_0=jdbc:clickhouse://127.0.0.1:${CLICKHOUSE_HTTP_PORT}/dc?compression=true
CLICKHOUSE.DBUsername_0=${CLICKHOUSE_USERNAME}
CLICKHOUSE.DBPasswd_0=${CLICKHOUSE_PASSWORD}
CLICKHOUSE.DBIsEncrypt_0=false
CLICKHOUSE.DBMaxCount_0=20
CLICKHOUSE.DBMinCount_0=2
CLICKHOUSE.DBConnOutTime_0=3000
CLICKHOUSE.DBAsyncInsert_0=1
CLICKHOUSE.DBAsyncInsertMaxInternet_0=2000
EOF

cat > "${CONTROL_ROOT}/ATSConfig.ini" <<EOF
REGISTER.ServerList=REGISTER.Svr1
REGISTER.Svr1.Name=REGISTER1
REGISTER.Svr1.Host=127.0.0.1:${ZOOKEEPER_PORT}

NetType=dps
ProtoVersion=${PROTO_VERSION}
EOF

append_server() {
  local key="$1"
  local name="$2"
  local port="$3"
  local service_name="$4"
  cat >> "${CONTROL_ROOT}/ATSConfig.ini" <<EOF

SERVER.${key}.Name=${name}
SERVER.${key}.Host=127.0.0.1:${port}
SERVER.${key}.RegType=2
SERVER.${key}.RegisterEnable=1
SERVER.${key}.LBFactor=1
SERVER.${key}.ServiceName=${service_name}
SERVER.${key}.RegisterServerList=REGISTER.Svr1
EOF
}

if [[ "${ORDER_CLUSTER_ENABLED}" == "true" ]]; then
  cat >> "${CONTROL_ROOT}/ATSConfig.ini" <<EOF

SERVER.OrderSvr.Name=OrderSvr
SERVER.OrderSvr.Host=127.0.0.1:33999
SERVER.OrderSvr.RegType=0
SERVER.OrderSvr.RegisterEnable=1
SERVER.OrderSvr.LBFactor=1
SERVER.OrderSvr.ServiceName=OrderSvr
SERVER.OrderSvr.RegisterServerList=REGISTER.Svr1
EOF
  append_server OrderSvrA OrderSvrA "${ORDERSVR_GW_PORT}" OrderSvrA
  append_server OrderSvrB OrderSvrB "${ORDERSVR_B_GW_PORT}" OrderSvrB
  if [[ "${ORDER_CLUSTER_C_ENABLED}" == "true" ]]; then
    append_server OrderSvrC OrderSvrC "${ORDERSVR_C_GW_PORT}" OrderSvrC
  fi
else
  append_server OrderSvr OrderSvr "${ORDERSVR_GW_PORT}" OrderSvr
fi
append_server APSSvr APSSvr "${APSSVR_GW_PORT}" APSSvr
if [[ "${TRADE_CLUSTER_ENABLED}" == "true" ]]; then
  cat >> "${CONTROL_ROOT}/ATSConfig.ini" <<EOF

SERVER.TradeSvr.Name=TradeSvr
SERVER.TradeSvr.Host=127.0.0.1:33997
SERVER.TradeSvr.RegType=0
SERVER.TradeSvr.RegisterEnable=1
SERVER.TradeSvr.LBFactor=1
SERVER.TradeSvr.ServiceName=TradeSvr
SERVER.TradeSvr.RegisterServerList=REGISTER.Svr1
EOF
  append_server TradeSvrA TradeSvrA "${TRADESVR_GW_PORT}" TradeSvrA
  append_server TradeSvrB TradeSvrB "${TRADESVR_B_GW_PORT}" TradeSvrB
else
  append_server TradeSvr TradeSvr "${TRADESVR_GW_PORT}" TDSvr
fi
if [[ "${MD_CLUSTER_ENABLED}" == "true" ]]; then
  cat >> "${CONTROL_ROOT}/ATSConfig.ini" <<EOF

SERVER.MDSvr.Name=MDSvr
SERVER.MDSvr.Host=127.0.0.1:33998
SERVER.MDSvr.RegType=0
SERVER.MDSvr.RegisterEnable=1
SERVER.MDSvr.LBFactor=1
SERVER.MDSvr.ServiceName=MDSvr
SERVER.MDSvr.RegisterServerList=REGISTER.Svr1
EOF
  append_server MDSvrA MDSvrA "${MDSVR_GW_PORT}" MDSvrA
  append_server MDSvrB MDSvrB "${MDSVR_B_GW_PORT}" MDSvrB
  if [[ "${MD_CLUSTER_C_ENABLED}" == "true" ]]; then
    append_server MDSvrC MDSvrC "${MDSVR_C_GW_PORT}" MDSvrC
  fi
else
  append_server MDSvr MDSvr "${MDSVR_GW_PORT}" MDSvr
fi
append_server LoginSvr LoginSvr "${LOGINSVR_GW_PORT}" LoginSvr
append_server AdminSvr AdminSvr "${ADMINSVR_GW_PORT}" AdminSvr
append_server LiqSvr LiqSvr "${LIQSVR_GW_PORT}" LiqSvr
append_server ManagerSvr ManagerSvr "${MANAGERSVR_GW_PORT}" ManagerSvr
append_server ProjectionSvr ProjectionSvr "${PROJECTIONSVR_GW_PORT}" ProjectionSvr

if [[ "${ORDER_CLUSTER_ENABLED}" == "true" || "${MD_CLUSTER_ENABLED}" == "true" || "${TRADE_CLUSTER_ENABLED}" == "true" ]]; then
  cat >> "${CONTROL_ROOT}/ATSConfig.ini" <<'EOF'

Cluster.Enabled=true
EOF
fi

if [[ "${TRADE_CLUSTER_ENABLED}" == "true" ]]; then
  cat >> "${CONTROL_ROOT}/ATSConfig.ini" <<'EOF'

LBConfig.TradeSvr=Partition
Cluster.TradeSvr.Enabled=true
Cluster.TradeSvrA.Enabled=true
Cluster.TradeSvrB.Enabled=true
Partition.TradeSvr.Count=256
Partition.TradeSvr.Root=/dc/cluster/tradesvr/partitions
Partition.TradeSvr.EnforceFence=true
Partition.TradeSvr.PlacementEnabled=false
Partition.TradeSvr.PlacementRequired=true
Partition.TradeSvr.PlacementPath=/dc/cluster/tradesvr/desired/placement
Partition.TradeSvrA.Count=256
Partition.TradeSvrA.Root=/dc/cluster/tradesvr/partitions
Partition.TradeSvrA.EnforceFence=true
Partition.TradeSvrA.EnforceReadiness=true
Partition.TradeSvrA.PlacementEnabled=false
Partition.TradeSvrA.PlacementRequired=true
Partition.TradeSvrA.PlacementPath=/dc/cluster/tradesvr/desired/placement
Partition.TradeSvrB.Count=256
Partition.TradeSvrB.Root=/dc/cluster/tradesvr/partitions
Partition.TradeSvrB.EnforceFence=true
Partition.TradeSvrB.EnforceReadiness=true
Partition.TradeSvrB.PlacementEnabled=false
Partition.TradeSvrB.PlacementRequired=true
Partition.TradeSvrB.PlacementPath=/dc/cluster/tradesvr/desired/placement
EOF
fi

if [[ "${ORDER_CLUSTER_ENABLED}" == "true" ]]; then
  cat >> "${CONTROL_ROOT}/ATSConfig.ini" <<'EOF'

LBConfig.OrderSvr=Partition
Cluster.OrderSvr.Enabled=true
Cluster.OrderSvrA.Enabled=true
Cluster.OrderSvrB.Enabled=true
Partition.OrderSvr.Count=256
Partition.OrderSvr.Root=/dc/cluster/ordersvr/partitions
Partition.OrderSvr.EnforceFence=true
Partition.OrderSvr.PlacementEnabled=false
Partition.OrderSvr.PlacementRequired=true
Partition.OrderSvr.PlacementPath=/dc/cluster/ordersvr/desired/placement
Partition.OrderSvrA.Count=256
Partition.OrderSvrA.Root=/dc/cluster/ordersvr/partitions
Partition.OrderSvrA.EnforceFence=true
Partition.OrderSvrA.EnforceReadiness=true
Partition.OrderSvrA.PlacementEnabled=false
Partition.OrderSvrA.PlacementRequired=true
Partition.OrderSvrA.PlacementPath=/dc/cluster/ordersvr/desired/placement
Partition.OrderSvrB.Count=256
Partition.OrderSvrB.Root=/dc/cluster/ordersvr/partitions
Partition.OrderSvrB.EnforceFence=true
Partition.OrderSvrB.EnforceReadiness=true
Partition.OrderSvrB.PlacementEnabled=false
Partition.OrderSvrB.PlacementRequired=true
Partition.OrderSvrB.PlacementPath=/dc/cluster/ordersvr/desired/placement
EOF
  if [[ "${ORDER_CLUSTER_C_ENABLED}" == "true" ]]; then
    cat >> "${CONTROL_ROOT}/ATSConfig.ini" <<'EOF'
Cluster.OrderSvrC.Enabled=true
Partition.OrderSvrC.Count=256
Partition.OrderSvrC.Root=/dc/cluster/ordersvr/partitions
Partition.OrderSvrC.EnforceFence=true
Partition.OrderSvrC.EnforceReadiness=true
Partition.OrderSvrC.PlacementEnabled=false
Partition.OrderSvrC.PlacementRequired=true
Partition.OrderSvrC.PlacementPath=/dc/cluster/ordersvr/desired/placement
EOF
  fi
fi

if [[ "${MD_CLUSTER_ENABLED}" == "true" ]]; then
  cat >> "${CONTROL_ROOT}/ATSConfig.ini" <<'EOF'

LBConfig.MDSvr=Partition
Cluster.MDSvr.Enabled=true
Cluster.MDSvrA.Enabled=true
Cluster.MDSvrB.Enabled=true
Partition.MDSvr.Count=256
Partition.MDSvr.Root=/dc/cluster/mdsvr/partitions
Partition.MDSvr.EnforceFence=true
Partition.MDSvr.PlacementEnabled=false
Partition.MDSvr.PlacementRequired=true
Partition.MDSvr.PlacementPath=/dc/cluster/mdsvr/desired/placement
Partition.MDSvrA.Count=256
Partition.MDSvrA.Root=/dc/cluster/mdsvr/partitions
Partition.MDSvrA.EnforceFence=true
Partition.MDSvrA.EnforceReadiness=true
Partition.MDSvrA.PlacementEnabled=false
Partition.MDSvrA.PlacementRequired=true
Partition.MDSvrA.PlacementPath=/dc/cluster/mdsvr/desired/placement
Partition.MDSvrB.Count=256
Partition.MDSvrB.Root=/dc/cluster/mdsvr/partitions
Partition.MDSvrB.EnforceFence=true
Partition.MDSvrB.EnforceReadiness=true
Partition.MDSvrB.PlacementEnabled=false
Partition.MDSvrB.PlacementRequired=true
Partition.MDSvrB.PlacementPath=/dc/cluster/mdsvr/desired/placement
EOF
  if [[ "${MD_CLUSTER_C_ENABLED}" == "true" ]]; then
    cat >> "${CONTROL_ROOT}/ATSConfig.ini" <<'EOF'
Cluster.MDSvrC.Enabled=true
Partition.MDSvrC.Count=256
Partition.MDSvrC.Root=/dc/cluster/mdsvr/partitions
Partition.MDSvrC.EnforceFence=true
Partition.MDSvrC.EnforceReadiness=true
Partition.MDSvrC.PlacementEnabled=false
Partition.MDSvrC.PlacementRequired=true
Partition.MDSvrC.PlacementPath=/dc/cluster/mdsvr/desired/placement
EOF
  fi
fi

install -m 0600 "${SCRIPT_DIR}/control.prod/jaas.ini" "${CONTROL_ROOT}/jaas.ini"
# The official image drops from root to its zookeeper user before starting.
# Keep the server-only mount readable inside that container; CONTROL_ROOT
# itself remains restricted to the deployment account.
install -m 0644 "${SCRIPT_DIR}/control.prod/jaas.ini" "${CONTROL_ROOT}/zookeeper-jaas.ini"
install -m 0600 "${SCRIPT_DIR}/control.prod/dc.dat" "${CONTROL_ROOT}/dc.dat"

cat > "${CONTROL_ROOT}/clickhouse-ports.xml" <<EOF
<clickhouse>
    <http_port>${CLICKHOUSE_HTTP_PORT}</http_port>
    <tcp_port>${CLICKHOUSE_NATIVE_PORT}</tcp_port>
    <interserver_http_port>39009</interserver_http_port>
</clickhouse>
EOF
chmod 0644 "${CONTROL_ROOT}/clickhouse-ports.xml"

cat > "${CONTROL_ROOT}/clickhouse-client.xml" <<EOF
<config>
    <host>127.0.0.1</host>
    <port>${CLICKHOUSE_NATIVE_PORT}</port>
</config>
EOF
chmod 0644 "${CONTROL_ROOT}/clickhouse-client.xml"

# Replace the container image's wildcard listener fragment. All SaaS services
# use host networking on this single node, so ClickHouse must remain local.
cat > "${CONTROL_ROOT}/clickhouse-docker-related.xml" <<'EOF'
<clickhouse>
    <listen_host>::1</listen_host>
    <listen_host>127.0.0.1</listen_host>
    <listen_try>1</listen_try>
</clickhouse>
EOF
chmod 0644 "${CONTROL_ROOT}/clickhouse-docker-related.xml"

cat > "${OVERRIDE_ROOT}/LoginSvr/config/application.properties" <<EOF
serverKey=SERVER.LoginSvr
log4j.file=./config/log4j.ini
log4j.thread=1
log4j.writeTime=true
log4j.async=true

server.servlet.context-path=/dc
server.address=127.0.0.1
server.port=${LOGINSVR_HTTP_PORT}

dbpool.cfg=../../control/DBPoolConfig.ini
dbpool.default=MYSQL0
dbType=mysql
defaultStartId=500000
defaultPwd=${LOGIN_DEFAULT_PASSWORD}
isSignature=0
validTime=3600
checkInterval=60
EOF

write_md_config() {
  local node="$1"
  cat > "${OVERRIDE_ROOT}/${node}/config/application.properties" <<EOF
serverKey=SERVER.${node}
orderServerKey=SERVER.OrderSvr
md.cluster.defaultMarketIndicator=4
log4j.file=./config/log4j.ini
log4j.thread=1
log4j.writeTime=true
log4j.async=true

dbpool.cfg=../../control/DBPoolConfig.ini
dbType=mysql
clickhouse.default=ClickHouse1

[ohlc]
ohlcStorePath=../../data/${node}/ohlc
ohlcBackPath=../../data/${node}/backup/ohlc
ohlcList=1W;true;false;yyyyww;true;true|1N;true;false;yyyyMM;true;true|1Y;true;false;yyyy;true;true|1D;true;false;yyyyMMdd;true;false|1M;true;true;HHmmss;true;false|5M;true;true;HHmmss;true;false|15M;true;true;HHmmss;true;false|30M;true;true;HHmmss;true;false|1H;true;true;HHmmss;true;true|2H;true;true;HHmmss;true;true|4H;true;true;HHmmss;true;true
ohlcVolumeFlag=false

[index]
indexList=APS
enableOrderFlag=true
enableDepthDiff=true
enableBookTicker=true
enablePartialDepth=true
enablePartialDepth5=false
enablePartialDepth10=true
enablePartialDepth20=false
compatOrderBookPublishIntervalMs=0
partialDepthPublishIntervalMs=0
compatIncompleteGraceMs=0
enablePerfStats=true
perfStatsPeriodSeconds=10
enableIndexOrderBookFlag=false
enableIndexMarkPriceFlag=true
enableIndexTickerFlag=true
enableTradeFlag=true
EOF

  cat > "${OVERRIDE_ROOT}/${node}/config/log4j.ini" <<EOF
log4j.rootLogger=error,file,stdout
log4j.logger.com.app.dc.service.cluster.MdPartitionRuntime=INFO,file,stdout
log4j.additivity.com.app.dc.service.cluster.MdPartitionRuntime=false

log4j.appender.file=org.apache.log4j.DailyRollingFileAppender
log4j.appender.file.File=../../log/${node}.log
log4j.appender.file.Append=true
log4j.appender.file.layout=org.apache.log4j.PatternLayout
log4j.appender.file.layout.ConversionPattern=%d{yyyy/MM/dd HH:mm:ss.SSS} %p %m (%C{1}:%L)%n
log4j.appender.stdout=org.apache.log4j.ConsoleAppender
log4j.appender.stdout.Target=System.out
log4j.appender.stdout.follow=true
log4j.appender.stdout.layout=org.apache.log4j.PatternLayout
log4j.appender.stdout.layout.ConversionPattern=%d{yyyy/MM/dd HH:mm:ss.SSS} %p %m (%C{1}:%L)%n
EOF
}

write_md_config MDSvr
if [[ "${MD_CLUSTER_ENABLED}" == "true" ]]; then
  write_md_config MDSvrA
  write_md_config MDSvrB
  if [[ "${MD_CLUSTER_C_ENABLED}" == "true" ]]; then
    write_md_config MDSvrC
  fi
fi

cat > "${OVERRIDE_ROOT}/APSSvr/config/application.properties" <<EOF
serverKey=SERVER.APSSvr
log4j.file=./config/log4j.ini
log4j.thread=1
log4j.writeTime=true
log4j.async=true

[BNFutures]
enableBinanceFlag=true
enableBookTickerFlag=true
enableTradeFlag=true
enablePartialDepthFlag=true
partialDepthLevels=10
partialDepthSpeedMs=100
enableSymbolTickerFlag=true
enableMarkPriceFlag=true
enableUserDataFlag=${APSSVR_ENABLE_USER_DATA}
enableKlineFlag=false
text=5m
limitQps=100
apiUrl=${APSSVR_BINANCE_REST_URL}
wssUrl=${APSSVR_BINANCE_WS_URL}

[BirdEye]
enableJupFlag=false
BirdEyeEnableFlag=false

[BNSpot]
BNSpotEnableFlag=false

dbpool.cfg=../../control/DBPoolConfig.ini
dbpool.default=MYSQL0
binanceSymbolList=${APSSVR_SYMBOLS}
binanceSymbolAliasList=${APSSVR_SYMBOL_ALIASES}
schedule.Config=./config/quartz.properties
storePath=../../data/APSSvr
sleepTime=0
EOF

cat > "${OVERRIDE_ROOT}/OrderSvr/config/application.properties" <<EOF
dbType=mysql
execOrderType=trade
orderStorePath=../../data/OrderSvr
serverKey=SERVER.OrderSvr
tradeServerKey=SERVER.TradeSvr
enableMarketPrice=true
enableSaveDBDemo=false
enableDepthDiff=true
enableFullOrderBookOnChange=true
fullOrderBookPublishIntervalMs=1000
depthDiffPublishIntervalMs=0
bookTickerPublishOnQtyChange=true
bookTickerPublishIntervalMs=0
order.selfTradePreventionMode=${ORDER_SELF_TRADE_PREVENTION_MODE:-CANCEL_TAKER}
enablePerfStats=true
perfStatsPeriodSeconds=10
log4j.file=./config/log4j.ini
log4j.thread=1
log4j.writeTime=true
log4j.async=true
dbpool.cfg=../../control/DBPoolConfig.ini
dbpool.default=MYSQL0
EOF

write_cluster_order_config() {
  local node="$1" replication_port="$2"
  local peers="OrderSvrA=127.0.0.1:${ORDERSVR_A_REPLICATION_PORT},OrderSvrB=127.0.0.1:${ORDERSVR_B_REPLICATION_PORT}"
  if [[ "${ORDER_CLUSTER_C_ENABLED}" == "true" ]]; then
    peers="${peers},OrderSvrC=127.0.0.1:${ORDERSVR_C_REPLICATION_PORT}"
  fi
  cat > "${OVERRIDE_ROOT}/${node}/config/application.properties" <<EOF
dbType=rockdb
execOrderType=trade
orderStorePath=../../data/${node}/store
serverKey=SERVER.${node}
tradeServerKey=SERVER.TradeSvr
order.cluster.serviceName=SERVER.OrderSvr
order.cluster.journal.enabled=true
order.cluster.journal.required=true
order.cluster.journalDir=../../data/${node}/journal
order.cluster.state.enabled=true
order.cluster.state.required=true
order.cluster.state.replication.required=true
order.cluster.commit.enabled=true
order.cluster.commit.required=true
order.cluster.snapshot.enabled=true
order.cluster.snapshotDir=../../data/${node}/snapshot
order.cluster.snapshot.barrier.enabled=true
order.cluster.snapshot.barrier.required=true
order.cluster.snapshot.barrier.acquireTimeoutMillis=10000
order.cluster.snapshot.promotionBarrier.required=true
order.cluster.snapshot.periodic.enabled=${ORDER_CLUSTER_PERIODIC_SNAPSHOT_ENABLED}
order.cluster.snapshot.periodic.pollMillis=${ORDER_CLUSTER_PERIODIC_SNAPSHOT_POLL_MILLIS}
order.cluster.snapshot.periodic.maxAgeMillis=${ORDER_CLUSTER_PERIODIC_SNAPSHOT_MAX_AGE_MILLIS}
order.cluster.snapshot.periodic.minCommittedMutations=${ORDER_CLUSTER_PERIODIC_SNAPSHOT_MIN_COMMITTED_MUTATIONS}
order.cluster.snapshot.periodic.maxPartitionsPerRun=${ORDER_CLUSTER_PERIODIC_SNAPSHOT_MAX_PARTITIONS_PER_RUN}
order.cluster.lifecycle.enabled=true
order.cluster.lifecycle.bootstrap.enabled=true
order.cluster.lifecycle.sameEpochRestart.enabled=true
order.cluster.lifecycle.pollMillis=1000
order.cluster.lifecycle.retryMillis=5000
order.cluster.perfProbe.enabled=false
order.cluster.recovery.rollbackUncommittedTail.enabled=true
order.cluster.replication.enabled=true
order.cluster.replication.required=true
order.cluster.replication.bindHost=127.0.0.1
order.cluster.replication.port=${replication_port}
order.cluster.replication.requestTimeoutMs=10000
order.cluster.replication.consistencyMode=${ORDER_CLUSTER_REPLICATION_CONSISTENCY_MODE}
order.cluster.replication.batch.maxRecords=${ORDER_CLUSTER_REPLICATION_BATCH_MAX_RECORDS}
order.cluster.replication.batch.maxWaitMicros=${ORDER_CLUSTER_REPLICATION_BATCH_MAX_WAIT_MICROS}
order.cluster.replication.batch.threads=${ORDER_CLUSTER_REPLICATION_BATCH_THREADS}
order.cluster.replication.async.retryMillis=${ORDER_CLUSTER_REPLICATION_ASYNC_RETRY_MILLIS}
order.cluster.replication.async.maxPendingRecords=${ORDER_CLUSTER_REPLICATION_ASYNC_MAX_PENDING_RECORDS}
order.cluster.replication.catchupBatchRecords=256
order.cluster.replication.crossEpochSnapshotRebase.enabled=true
order.cluster.replication.peers=${peers}
order.cluster.defaultMarketIndicator=4
order.projection.enabled=false
order.projection.serverKey=SERVER.ProjectionSvr
# Consumer-owned binary projection path. ProjectionSvr owns durable watermark/GAP recovery.
order.projection.binary.enabled=true
order.projection.binary.publishBatchSize=64
order.projection.binary.maxBatchBytes=16777216
order.tenantSymbolRules.enabled=true
enableMarketPrice=true
enableSaveDBDemo=false
enableDepthDiff=true
enableFullOrderBookOnChange=true
fullOrderBookPublishIntervalMs=1000
depthDiffPublishIntervalMs=0
bookTickerPublishOnQtyChange=true
bookTickerPublishIntervalMs=0
order.selfTradePreventionMode=${ORDER_SELF_TRADE_PREVENTION_MODE:-CANCEL_TAKER}
enablePerfStats=true
perfStatsPeriodSeconds=10
log4j.file=./config/log4j.ini
log4j.thread=1
log4j.writeTime=true
log4j.async=true
dbpool.cfg=../../control/DBPoolConfig.ini
dbpool.default=MYSQL0
EOF
}

cat > "${OVERRIDE_ROOT}/ProjectionSvr/config/application.properties" <<EOF
serverKey=SERVER.ProjectionSvr
log4j.file=./config/log4j.ini
log4j.thread=1
log4j.writeTime=true
log4j.async=true
dbpool.cfg=../../control/DBPoolConfig.ini
dbpool.default=MYSQL0
projection.saveDemo=false
projection.binary.enabled=${ORDER_CLUSTER_ENABLED}
projection.binary.orderServerKey=SERVER.OrderSvr
projection.binary.fetchMaxRecords=500
projection.binary.fetchTimeoutMs=5000
projection.binary.retryMs=1000
projection.binary.subscriptionRefreshMs=5000
projection.binary.safetyPollMillis=1000
projection.binary.safetyPollPartitionsPerRun=16
projection.binary.workerStripes=4
projection.binary.maxBufferedBatchesPerPartition=1024
projection.trade.binary.enabled=${TRADE_CLUSTER_ENABLED}
projection.trade.binary.tradeServerKey=SERVER.TradeSvr
EOF

if [[ "${ORDER_CLUSTER_ENABLED}" == "true" ]]; then
  write_cluster_order_config OrderSvrA "${ORDERSVR_A_REPLICATION_PORT}"
  write_cluster_order_config OrderSvrB "${ORDERSVR_B_REPLICATION_PORT}"
  if [[ "${ORDER_CLUSTER_C_ENABLED}" == "true" ]]; then
    write_cluster_order_config OrderSvrC "${ORDERSVR_C_REPLICATION_PORT}"
  fi
fi

write_trade_config() {
  local node="$1" business_enabled="$2" replication_port="${3:-}"
  local peers=""
  if [[ "${TRADE_CLUSTER_ENABLED}" == "true" ]]; then
    peers="TradeSvrA=127.0.0.1:${TRADESVR_A_REPLICATION_PORT},TradeSvrB=127.0.0.1:${TRADESVR_B_REPLICATION_PORT}"
  fi
  cat > "${OVERRIDE_ROOT}/${node}/config/application.properties" <<EOF
[Cron]
schedule.Config=./config/quartz.properties
serverKey=SERVER.${node}
log4j.file=./config/log4j.ini
log4j.thread=1
log4j.writeTime=true
log4j.async=true
storePath=../../data/${node}
enableSaveDBDemo=false
allowMissingMarkPrice=${TRADE_ALLOW_MISSING_MARK_PRICE:-false}
trade.executionDedupe.maxEntries=${TRADE_EXECUTION_DEDUPE_MAX_ENTRIES:-1000000}
trade.node.businessEnabled=${business_enabled}
trade.cluster.serviceName=SERVER.TradeSvr
trade.cluster.journal.enabled=${TRADE_CLUSTER_ENABLED}
trade.cluster.journal.path=../../data/${node}/journal
trade.cluster.state.commit.enabled=${TRADE_CLUSTER_ENABLED}
trade.cluster.state.required=${TRADE_CLUSTER_ENABLED}
trade.cluster.snapshot.enabled=${TRADE_CLUSTER_ENABLED}
trade.cluster.snapshot.path=../../data/${node}/snapshot
trade.cluster.snapshot.periodic.enabled=false
trade.cluster.lifecycle.enabled=${TRADE_CLUSTER_ENABLED}
trade.cluster.recovery.authoritative=${TRADE_CLUSTER_ENABLED}
trade.cluster.lifecycle.pollMillis=1000
trade.cluster.lifecycle.retryMillis=5000
trade.cluster.replication.enabled=${TRADE_CLUSTER_ENABLED}
trade.cluster.replication.bindHost=127.0.0.1
trade.cluster.replication.port=${replication_port:-19092}
trade.cluster.replication.requestTimeoutMs=10000
trade.cluster.replication.catchupBatchRecords=256
trade.cluster.replication.peers=${peers}
trade.projection.binary.enabled=${TRADE_CLUSTER_ENABLED}
trade.projection.binary.topicPrefix=dc.trade.committed.
trade.projection.binary.maxBatchBytes=16777216
dbType=mysql
dbpool.cfg=../../control/DBPoolConfig.ini
dbpool.default=MYSQL0
EOF
}

if [[ "${TRADE_CLUSTER_ENABLED}" == "true" ]]; then
  # Both nodes initialize the hot runtime. Partition Primary + READY fencing
  # controls business writes; replicas keep state warm for promotion.
  write_trade_config TradeSvrA true "${TRADESVR_A_REPLICATION_PORT}"
  write_trade_config TradeSvrB true "${TRADESVR_B_REPLICATION_PORT}"
else
  write_trade_config TradeSvr true
fi

# TradeSvr's successful order/execution path is intentionally quieter than the
# default image configuration. At sustained matching rates those messages are
# emitted several times per fill to both a file and stdout, creating needless
# I/O and cgroup page-cache pressure. Warnings, failures and lifecycle events
# remain at INFO/WARN through the root logger.
write_trade_log_config() {
  local node="$1"
  cat > "${OVERRIDE_ROOT}/${node}/config/log4j.ini" <<EOF
log4j.rootLogger=INFO,file,stdout

log4j.appender.file=org.apache.log4j.DailyRollingFileAppender
log4j.appender.file.File=../../log/${node}.log
log4j.appender.file.Append=true
log4j.appender.file.layout=org.apache.log4j.PatternLayout
log4j.appender.file.layout.ConversionPattern=%d{yyyy/MM/dd HH:mm:ss.SSS} %p %m (%C{1}:%L)%n

log4j.appender.stdout=org.apache.log4j.ConsoleAppender
log4j.appender.stdout.Target=System.out
log4j.appender.stdout.follow=true
log4j.appender.stdout.layout=org.apache.log4j.PatternLayout
log4j.appender.stdout.layout.ConversionPattern=%d{yyyy/MM/dd HH:mm:ss.SSS} %p %m (%C{1}:%L)%n

log4j.logger.com.app.dc.service.check.ProcessOrder=WARN
log4j.logger.com.app.dc.service.order.OrderManager=WARN
log4j.logger.com.app.dc.handler.UpdateOrderHandler=WARN
EOF
}

if [[ "${TRADE_CLUSTER_ENABLED}" == "true" ]]; then
  write_trade_log_config TradeSvrA
  write_trade_log_config TradeSvrB
else
  write_trade_log_config TradeSvr
fi

cat > "${OVERRIDE_ROOT}/LiqSvr/config/application.properties" <<EOF
tradeServerKey=SERVER.TradeSvr
serverKey=SERVER.LiqSvr
log4j.file=./config/log4j.ini
log4j.thread=1
log4j.writeTime=true
log4j.async=true
storePath=../../data/LiqSvr
dbpool.cfg=../../control/DBPoolConfig.ini
dbpool.default=MYSQL0
liquidation.partialEnabled=${LIQUIDATION_PARTIAL_ENABLED:-true}
liquidation.partialRatio=${LIQUIDATION_PARTIAL_RATIO:-0.25}
EOF

cat > "${OVERRIDE_ROOT}/ManagerSvr/config/application.properties" <<EOF
serverKey=SERVER.ManagerSvr
log4j.file=./config/log4j.ini
log4j.thread=1
log4j.writeTime=true
log4j.async=true
dbpool.cfg=../../control/DBPoolConfig.ini
dbpool.default=MYSQL0
symbolCategory=BTC|ETH|USDT
encryptionType=2
EOF

cat > "${OVERRIDE_ROOT}/AdminSvr/config/application.properties" <<EOF
serverKey=SERVER.AdminSvr
log4j.file=./config/log4j.ini
log4j.thread=1
log4j.writeTime=true
log4j.async=true
dbpool.cfg=../../control/DBPoolConfig.ini
dbpool.default=MYSQL0
clickhouse.default=ClickHouse1
dbpool.event=MYSQL1
loadSymbolCron=0 0/10 * * * ?
codeCheckDate=false
ConvertCurrency=USDT
level1Rebate=0.4
level2Rebate=0
EOF

cat > "${OVERRIDE_ROOT}/GW/config/spring-tcp-server.xml" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<beans xmlns="http://www.springframework.org/schema/beans"
       xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
       xsi:schemaLocation="http://www.springframework.org/schema/beans http://www.springframework.org/schema/beans/spring-beans-4.3.xsd">
  <bean id="tcpServer" class="com.gateway.connector.tcp.server.TServer" init-method="init" destroy-method="shutdown">
    <property name="port" value="${GW_TCP_PORT}"/>
    <property name="serverConfig" ref="serverConfig"/>
  </bean>
  <bean id="webSocketServer" class="com.gateway.connector.tcp.server.WebSocketServer" init-method="init" destroy-method="shutdown">
    <property name="port" value="${GW_WEBSOCKET_PORT}"/>
    <property name="serverConfig" ref="webSocketServerConfig"/>
  </bean>
  <bean id="httpServer" class="com.gateway.connector.tcp.server.HttpServer" init-method="init" destroy-method="shutdown">
    <property name="port" value="${GW_HTTP_PORT}"/>
    <property name="serverConfig" ref="serverConfig"/>
  </bean>
  <bean id="tcpSessionManager" class="com.gateway.connector.tcp.TcpSessionManager">
    <property name="maxInactiveInterval" value="500"/>
    <property name="topicManager" ref="topicManager"/>
    <property name="sessionListeners"><list><ref bean="logSessionListener"/></list></property>
  </bean>
  <bean id="logSessionListener" class="com.gateway.connector.api.listener.LogSessionListener"/>
  <bean id="tcpSender" class="com.gateway.remoting.TcpSender"><property name="tcpConnector" ref="tcpConnector"/></bean>
  <bean id="serverConfig" class="com.gateway.connector.tcp.config.ServerTransportConfig">
    <property name="tcpConnector" ref="tcpConnector"/>
    <property name="proxy" ref="proxy"/>
    <property name="notify" ref="notify"/>
    <property name="gzip" value="true"/>
    <property name="login" value="true"/>
  </bean>
  <bean id="webSocketServerConfig" class="com.gateway.connector.tcp.config.ServerTransportConfig">
    <property name="tcpConnector" ref="tcpConnector"/>
    <property name="proxy" ref="proxy"/>
    <property name="notify" ref="notify"/>
    <property name="gzip" value="true"/>
    <property name="login" value="true"/>
  </bean>
  <bean id="tcpConnector" class="com.gateway.connector.tcp.TcpConnector" init-method="init" destroy-method="destroy">
    <property name="tcpSessionManager" ref="tcpSessionManager"/>
  </bean>
  <bean id="topicManager" class="com.gateway.invoke.TopicManager"/>
  <bean id="notify" class="com.gateway.notify.NotifyProxy">
    <property name="tcpConnector" ref="tcpConnector"/>
    <property name="topicManager" ref="topicManager"/>
  </bean>
</beans>
EOF

cat > "${OVERRIDE_ROOT}/GW/config/spring-gw-client.xml" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<beans xmlns="http://www.springframework.org/schema/beans"
       xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
       xsi:schemaLocation="http://www.springframework.org/schema/beans http://www.springframework.org/schema/beans/spring-beans-3.0.xsd">
  <bean id="proxy" class="com.app.gw.security.SaasGWProxy" init-method="init">
    <property name="topicManager" ref="topicManager"/>
    <property name="notifyProxy" ref="notify"/>
    <property name="tcpConnector" ref="tcpConnector"/>
    <property name="SessionService" value="LoginSvr"/>
    <property name="RequestService" value="AdminSvr,APSSvr,OrderSvr,TradeSvr,MDSvr,LoginSvr,ManagerSvr,LiqSvr,ProjectionSvr"/>
    <property name="Subscribes">
      <map>
        <entry key="LoginSvr" value="SYS.ATS.LOGIN|1dc.login.apikey"/>
        <entry key="MDSvr" value="dc.md.kline.**|dc.md.trade.**|dc.md.market.trade.**|dc.md.orderbook.**|dc.md.depth.**"/>
        <entry key="APSSvr" value="dc.aps|dc.aps.**|dc.bookticker.**|dc.trade.**"/>
        <entry key="OrderSvr" value="dc.order.status.**|dc.order.trade.**"/>
        <entry key="TradeSvr" value="dc.trade.accountbalance.**|dc.trade.position.**|dc.trade.posting.**"/>
      </map>
    </property>
    <property name="securityChecks"><list><ref bean="openApiIngressSecurityCheck"/><ref bean="openApiRateLimitSecurityCheck"/><ref bean="sqlInjSecurityCheck"/></list></property>
    <property name="filterTopics"><list><ref bean="apiKeyService"/><ref bean="openApiIngressSecurityCheck"/><ref bean="openApiRateLimitSecurityCheck"/></list></property>
    <property name="ApiKeyService" ref="apiKeyService"/>
    <property name="openApiRateLimitSecurityCheck" ref="openApiRateLimitSecurityCheck"/>
  </bean>
  <bean id="apiKeyService" class="com.gateway.invoke.filter.apikey.ApiKeyService"/>
  <bean id="openApiIngressSecurityCheck" class="com.app.gw.security.OpenApiIngressSecurityCheck"/>
  <bean id="openApiRateLimitSecurityCheck" class="com.app.gw.security.OpenApiRateLimitSecurityCheck">
    <property name="traderStandardQps" value="100"/>
    <property name="traderStandardBurst" value="30"/>
    <property name="tenantStandardQps" value="20"/>
    <property name="tenantStandardBurst" value="10"/>
  </bean>
  <bean id="limitSecurityCheck" class="com.gateway.invoke.security.LimitSecurityCheck" init-method="init">
    <property name="tcpSessionManager" ref="tcpSessionManager"/>
    <property name="limitQps" value="100"/>
  </bean>
  <bean id="sqlInjSecurityCheck" class="com.gateway.invoke.security.SqlInjSecurityCheck" init-method="init"/>
</beans>
EOF

chmod 0600 "${CONTROL_ROOT}/DBPoolConfig.ini" "${CONTROL_ROOT}/ATSConfig.ini"
find "${OVERRIDE_ROOT}" -type f -exec chmod 0600 {} +
log "Generated isolated SaaS configuration under ${CONTROL_ROOT}"
