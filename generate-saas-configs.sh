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

CONTROL_ROOT="${DEPLOY_ROOT}/control"
OVERRIDE_ROOT="${CONTROL_ROOT}/overrides"
umask 077

install -d -m 0750 "${CONTROL_ROOT}" "${OVERRIDE_ROOT}/GW/config" "${OVERRIDE_ROOT}/LoginSvr/config" "${OVERRIDE_ROOT}/MDSvr/config" "${OVERRIDE_ROOT}/APSSvr/config" "${OVERRIDE_ROOT}/OrderSvr/config" "${OVERRIDE_ROOT}/TradeSvr/config" "${OVERRIDE_ROOT}/LiqSvr/config" "${OVERRIDE_ROOT}/ManagerSvr/config" "${OVERRIDE_ROOT}/AdminSvr/config"

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

append_server OrderSvr OrderSvr "${ORDERSVR_GW_PORT}" OrderSvr
append_server APSSvr APSSvr "${APSSVR_GW_PORT}" APSSvr
append_server TradeSvr TradeSvr "${TRADESVR_GW_PORT}" TDSvr
append_server MDSvr MDSvr "${MDSVR_GW_PORT}" MDSvr
append_server LoginSvr LoginSvr "${LOGINSVR_GW_PORT}" LoginSvr
append_server AdminSvr AdminSvr "${ADMINSVR_GW_PORT}" AdminSvr
append_server LiqSvr LiqSvr "${LIQSVR_GW_PORT}" LiqSvr
append_server ManagerSvr ManagerSvr "${MANAGERSVR_GW_PORT}" ManagerSvr

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

cat > "${OVERRIDE_ROOT}/LoginSvr/config/application.properties" <<EOF
serverKey=SERVER.LoginSvr
log4j.file=./config/log4j.ini
log4j.thread=1
log4j.writeTime=true
log4j.async=true

server.servlet.context-path=/dc
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

cat > "${OVERRIDE_ROOT}/MDSvr/config/application.properties" <<EOF
serverKey=SERVER.MDSvr
orderServerKey=SERVER.OrderSvr
log4j.file=./config/log4j.ini
log4j.thread=1
log4j.writeTime=true
log4j.async=true

dbpool.cfg=../../control/DBPoolConfig.ini
dbType=mysql
clickhouse.default=ClickHouse1

[ohlc]
ohlcStorePath=../../data/MDSvr/ohlc
ohlcBackPath=../../data/MDSvr/backup/ohlc
ohlcList=1W;true;false;yyyyww;false;true|1N;true;false;yyyyMM;false;true|1Y;true;false;yyyy;false;true|1D;true;false;yyyyMMdd;false;false|1M;true;true;HHmmss;false;false|5M;true;true;HHmmss;false;false|15M;true;true;HHmmss;false;false|30M;true;true;HHmmss;false;false|1H;true;true;HHmmss;false;true|2H;true;true;HHmmss;false;true|4H;true;true;HHmmss;false;true
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
compatOrderBookPublishIntervalMs=1000
partialDepthPublishIntervalMs=1000
enablePerfStats=true
perfStatsPeriodSeconds=10
enableIndexOrderBookFlag=false
enableIndexMarkPriceFlag=true
enableIndexTickerFlag=true
enableTradeFlag=true
EOF

cat > "${OVERRIDE_ROOT}/APSSvr/config/application.properties" <<EOF
serverKey=SERVER.APSSvr
log4j.file=./config/log4j.ini
log4j.thread=1
log4j.writeTime=true
log4j.async=true

[BNFutures]
enableBinanceFlag=true
enableBookTickerFlag=true
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
enableMarketPrice=false
enableSaveDBDemo=false
enableDepthDiff=true
enableFullOrderBookOnChange=true
fullOrderBookPublishIntervalMs=1000
depthDiffPublishIntervalMs=200
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

cat > "${OVERRIDE_ROOT}/TradeSvr/config/application.properties" <<EOF
[Cron]
schedule.Config=./config/quartz.properties
serverKey=SERVER.TradeSvr
log4j.file=./config/log4j.ini
log4j.thread=1
log4j.writeTime=true
log4j.async=true
storePath=../../data/TradeSvr
enableSaveDBDemo=false
allowMissingMarkPrice=${TRADE_ALLOW_MISSING_MARK_PRICE:-false}
dbType=mysql
dbpool.cfg=../../control/DBPoolConfig.ini
dbpool.default=MYSQL0
EOF

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
    <property name="login" value="false"/>
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
  <bean id="proxy" class="com.gateway.invoke.gw.GWProxy" init-method="init">
    <property name="topicManager" ref="topicManager"/>
    <property name="notifyProxy" ref="notify"/>
    <property name="tcpConnector" ref="tcpConnector"/>
    <property name="SessionService" value="LoginSvr"/>
    <property name="RequestService" value="AdminSvr,APSSvr,OrderSvr,TDSvr,MDSvr,LoginSvr,ManagerSvr,LiqSvr"/>
    <property name="Subscribes">
      <map>
        <entry key="LoginSvr" value="SYS.ATS.LOGIN|1dc.login.apikey"/>
        <entry key="MDSvr" value="dc.md.kline.**|dc.md.trade.**|dc.md.depth.**"/>
        <entry key="APSSvr" value="dc.aps"/>
      </map>
    </property>
    <property name="securityChecks"><list><ref bean="sqlInjSecurityCheck"/></list></property>
    <property name="filterTopics"><list><ref bean="apiKeyService"/></list></property>
    <property name="ApiKeyService" ref="apiKeyService"/>
  </bean>
  <bean id="apiKeyService" class="com.gateway.invoke.filter.apikey.ApiKeyService"/>
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
