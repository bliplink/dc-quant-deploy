#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${1:-${ROOT_DIR}/.env.prod}"
VALIDATE_ENV_SCRIPT="${ROOT_DIR}/validate-env.sh"

require_file() {
  [[ -f "$1" ]] || {
    echo "Missing required file: $1" >&2
    exit 1
  }
}

load_env() {
  require_file "${ENV_FILE}"
  require_file "${VALIDATE_ENV_SCRIPT}"
  bash "${VALIDATE_ENV_SCRIPT}" "${ENV_FILE}"
  # shellcheck disable=SC1090
  set -a && . "${ENV_FILE}" && set +a
  : "${DEPLOY_ROOT:?DEPLOY_ROOT is required}"
}

write_file() {
  local file="$1"
  local dir
  dir="$(dirname "${file}")"
  mkdir -p "${dir}"
  cat > "${file}"
  chmod 600 "${file}"
  if [[ -n "${RUNTIME_UID:-}" && -n "${RUNTIME_GID:-}" ]]; then
    chown "${RUNTIME_UID}:${RUNTIME_GID}" "${file}" 2>/dev/null || true
  fi
}

bool_from_secret() {
  local explicit="$1"
  local secret="$2"
  if [[ -n "${explicit}" ]]; then
    printf '%s\n' "${explicit}"
  elif [[ -n "${secret}" ]]; then
    printf 'true\n'
  else
    printf 'false\n'
  fi
}

load_env

QUANTSVR_BOT_TOKEN="${QUANTSVR_BOT_TOKEN:-}"
QUANTSVR_ENABLE_BOT="$(bool_from_secret "${QUANTSVR_ENABLE_BOT:-}" "${QUANTSVR_BOT_TOKEN}")"
QUANTSVR_BOT_USERNAME="${QUANTSVR_BOT_USERNAME:-}"
QUANTSVR_BOT_GROUP_ID="${QUANTSVR_BOT_GROUP_ID:-0}"
QUANTSVR_BOT_ADMIN_LIST="${QUANTSVR_BOT_ADMIN_LIST:-}"
APSSVR_ENABLE_USER_DATA="${APSSVR_ENABLE_USER_DATA:-false}"
GW_TCP_PORT="${GW_TCP_PORT:-3000}"
GW_WEBSOCKET_PORT="${GW_WEBSOCKET_PORT:-3001}"
GATEWAY_PORT="${GATEWAY_PORT:-3002}"
LOGINSVR_HTTP_PORT="${LOGINSVR_HTTP_PORT:-19990}"
MDSVR_GW_PORT="${MDSVR_GW_PORT:-30028}"
APSSVR_GW_PORT="${APSSVR_GW_PORT:-30035}"
LOGINSVR_GW_PORT="${LOGINSVR_GW_PORT:-20034}"
QUANTSVR_GW_PORT="${QUANTSVR_GW_PORT:-30042}"
INDSVR_GW_PORT="${INDSVR_GW_PORT:-30044}"
SIMSVR_GW_PORT="${SIMSVR_GW_PORT:-30045}"
BATCHSVR_GW_PORT="${BATCHSVR_GW_PORT:-30046}"

INDSVR_DEEPSEEK_API_KEY="${INDSVR_DEEPSEEK_API_KEY:-}"
CLICKHOUSE_JDBC_URL="jdbc:clickhouse://${CLICKHOUSE_HOST}:${CLICKHOUSE_HTTP_PORT}/${CLICKHOUSE_DB_NAME}?compression=true"
CLICKHOUSE_JDBC_USERNAME="${CLICKHOUSE_USERNAME:-default}"
CLICKHOUSE_JDBC_PASSWORD="${CLICKHOUSE_PASSWORD:-}"

write_file "${DEPLOY_ROOT}/control/ATSConfig.ini" <<EOF
# Generated from .env.prod. Docker services keep their standard service names.
REGISTER.ServerList=REGISTER.Svr1

REGISTER.Svr1.Name=REGISTER1
REGISTER.Svr1.Host=127.0.0.1:2181

NetType=dps
ProtoVersion=1
ServerMonitor.Enable=true
ServerMonitor.EnableRouteMeta=true
ServerMonitor.RecentTopicLimit=20
ServerMonitor.RequestTouchMinIntervalMs=5000
ServerMonitor.NodeSnapshotPeriodSeconds=60
ServerMonitor.ConnectionSnapshotPeriodSeconds=60

SERVER.MDSvr.Name=MDSvr
SERVER.MDSvr.Host=127.0.0.1:${MDSVR_GW_PORT}
SERVER.MDSvr.RegType=2
SERVER.MDSvr.RegisterEnable=0
SERVER.MDSvr.LBFactor=1
SERVER.MDSvr.ServiceName=MDSvr
SERVER.MDSvr.RegisterServerList=REGISTER.Svr1

SERVER.APSSvr.Name=APSSvr
SERVER.APSSvr.Host=127.0.0.1:${APSSVR_GW_PORT}
SERVER.APSSvr.RegType=2
SERVER.APSSvr.RegisterEnable=0
SERVER.APSSvr.LBFactor=1
SERVER.APSSvr.ServiceName=APSSvr
SERVER.APSSvr.RegisterServerList=REGISTER.Svr1

SERVER.LoginSvr.Name=LoginSvr
SERVER.LoginSvr.Host=127.0.0.1:${LOGINSVR_GW_PORT}
SERVER.LoginSvr.RegType=2
SERVER.LoginSvr.RegisterEnable=0
SERVER.LoginSvr.LBFactor=1
SERVER.LoginSvr.ServiceName=ValidationServer
SERVER.LoginSvr.RegisterServerList=REGISTER.Svr1

SERVER.QuantSvr.Name=QuantSvr
SERVER.QuantSvr.Host=127.0.0.1:${QUANTSVR_GW_PORT}
SERVER.QuantSvr.RegType=2
SERVER.QuantSvr.RegisterEnable=0
SERVER.QuantSvr.LBFactor=1
SERVER.QuantSvr.ServiceName=QuantSvr
SERVER.QuantSvr.RegisterServerList=REGISTER.Svr1

SERVER.INDSvr.Name=INDSvr
SERVER.INDSvr.Host=127.0.0.1:${INDSVR_GW_PORT}
SERVER.INDSvr.RegType=2
SERVER.INDSvr.RegisterEnable=0
SERVER.INDSvr.LBFactor=1
SERVER.INDSvr.ServiceName=INDSvr
SERVER.INDSvr.RegisterServerList=REGISTER.Svr1

SERVER.SIMSvr.Name=SIMSvr
SERVER.SIMSvr.Host=127.0.0.1:${SIMSVR_GW_PORT}
SERVER.SIMSvr.RegType=2
SERVER.SIMSvr.RegisterEnable=0
SERVER.SIMSvr.LBFactor=1
SERVER.SIMSvr.ServiceName=SIMSvr
SERVER.SIMSvr.RegisterServerList=REGISTER.Svr1

SERVER.BatchSvr.Name=BatchSvr
SERVER.BatchSvr.Host=127.0.0.1:${BATCHSVR_GW_PORT}
SERVER.BatchSvr.RegType=2
SERVER.BatchSvr.RegisterEnable=0
SERVER.BatchSvr.LBFactor=1
SERVER.BatchSvr.ServiceName=BatchSvr
SERVER.BatchSvr.RegisterServerList=REGISTER.Svr1
EOF

write_file "${DEPLOY_ROOT}/control/overrides/GW/config/spring-gw-client.xml" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<beans xmlns="http://www.springframework.org/schema/beans"
	xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
	xsi:schemaLocation="http://www.springframework.org/schema/beans
                           http://www.springframework.org/schema/beans/spring-beans-3.0.xsd">
	<bean id="proxy" class="com.gateway.invoke.gw.GWProxy" init-method="init">
		<property name="topicManager" ref="topicManager" />
		<property name="notifyProxy" ref="notify" />
		<property name="tcpConnector" ref="tcpConnector" />
		<property name="mcpToolConfigPath" value="./config/mcpTools.tsv" />
		<property name="mcpReloadPeriod" value="1" />
		<property name="SessionService" value="" />
		<property name="RequestService" value="LoginSvr,MDSvr,APSSvr,QuantSvr,INDSvr,SIMSvr,BatchSvr" />
		<property name="Subscribes">
			<map>
				<entry key="MDSvr" value="dc.md.kline.**|dc.md.trade.**|md.monitor.**" />
				<entry key="APSSvr" value="dc.aps|aps.monitor.**" />
			</map>
		</property>
		<property name="securityChecks">
			<list><ref bean="apiKeySecurityCheck" /></list>
		</property>
		<property name="filterTopics">
			<list>
				<ref bean="apiKeyService" />
				<ref bean="serverMonitor" />
			</list>
		</property>
		<property name="ApiKeyService" ref="apiKeyService" />
		<property name="serverMonitor" ref="serverMonitor" />
	</bean>
	<bean id="serverMonitor" class="com.gateway.monitor.ServerMonitor">
		<property name="ingressConnectionMonitor" ref="ingressConnectionMonitor" />
	</bean>
	<bean id="apiKeyService" class="com.gateway.invoke.filter.apikey.ApiKeyService" />
	<bean id="limitSecurityCheck" class="com.gateway.invoke.security.LimitSecurityCheck" init-method="init">
		<property name="tcpSessionManager" ref="tcpSessionManager" />
		<property name="limitQps" value="100" />
	</bean>
	<bean id="sqlInjSecurityCheck" class="com.gateway.invoke.security.SqlInjSecurityCheck" init-method="init" />
	<bean id="apiKeySecurityCheck" class="com.gateway.invoke.security.APIKeySecurityCheck" init-method="init">
		<property name="apiKeyListPath" value="./config/apiKeyList.csv" />
		<property name="period" value="1" />
	</bean>
</beans>
EOF

write_file "${DEPLOY_ROOT}/control/DBPoolConfig.ini" <<EOF
# Generated from .env.prod. Do not edit this runtime copy directly.
CLICKHOUSE.DBCount=1
CLICKHOUSE.DBSourceName_0=ClickHouse1
CLICKHOUSE.DBUrl_0=${CLICKHOUSE_JDBC_URL}
CLICKHOUSE.DBUsername_0=${CLICKHOUSE_JDBC_USERNAME}
CLICKHOUSE.DBPasswd_0=${CLICKHOUSE_JDBC_PASSWORD}
CLICKHOUSE.DBIsEncrypt_0=false
CLICKHOUSE.DBMaxCount_0=50
CLICKHOUSE.DBMinCount_0=5
CLICKHOUSE.DBConnOutTime_0=1000
CLICKHOUSE.DBAsyncInsert_0=1
CLICKHOUSE.DBAsyncInsertMaxInternet_0=2000
EOF

write_file "${DEPLOY_ROOT}/control/overrides/LoginSvr/config/application.properties" <<EOF
server.servlet.context-path=/dc
server.port=${LOGINSVR_HTTP_PORT}

serverKey=SERVER.LoginSvr
log4j.file=./config/log4j.ini
log4j.thread=1
log4j.writeTime=true
log4j.async=true

dbpool.cfg=./config/DBPoolConfig.ini
dbpool.default=ClickHouse1
dbType=clickhouse
clickhouse.default=ClickHouse1

defaultStartId=500000
defaultPwd=123456
isSignature=0
validTime=3600
checkInterval=60
EOF

write_file "${DEPLOY_ROOT}/control/overrides/GW/config/spring-tcp-server.xml" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<beans xmlns="http://www.springframework.org/schema/beans"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://www.springframework.org/schema/beans http://www.springframework.org/schema/beans/spring-beans-4.3.xsd">
  <bean id="tcpServer" class="com.gateway.connector.tcp.server.TServer"
      init-method="init" destroy-method="shutdown">
    <property name="port" value="${GW_TCP_PORT}" />
    <property name="serverConfig" ref="serverConfig" />
  </bean>
  <bean id="webSocketServer" class="com.gateway.connector.tcp.server.WebSocketServer"
      init-method="init" destroy-method="shutdown">
    <property name="port" value="${GW_WEBSOCKET_PORT}" />
    <property name="serverConfig" ref="webSocketServerConfig" />
  </bean>
  <bean id="httpServer" class="com.gateway.connector.tcp.server.HttpServer"
      init-method="init" destroy-method="shutdown">
    <property name="port" value="${GATEWAY_PORT}" />
    <property name="serverConfig" ref="serverConfig" />
  </bean>
  <bean id="tcpSessionManager" class="com.gateway.connector.tcp.TcpSessionManager">
    <property name="maxInactiveInterval" value="500" />
    <property name="topicManager" ref="topicManager" />
    <property name="sessionListeners"><list><ref bean="logSessionListener" /></list></property>
  </bean>
  <bean id="logSessionListener" class="com.gateway.connector.api.listener.LogSessionListener" />
  <bean id="ingressConnectionMonitor" class="com.gateway.monitor.IngressConnectionMonitor" />
  <bean id="tcpSender" class="com.gateway.remoting.TcpSender">
    <property name="tcpConnector" ref="tcpConnector" />
  </bean>
  <bean id="serverConfig" class="com.gateway.connector.tcp.config.ServerTransportConfig">
    <property name="tcpConnector" ref="tcpConnector" />
    <property name="proxy" ref="proxy" />
    <property name="notify" ref="notify" />
    <property name="ingressConnectionMonitor" ref="ingressConnectionMonitor" />
    <property name="gzip" value="true" />
    <property name="login" value="false" />
  </bean>
  <bean id="webSocketServerConfig" class="com.gateway.connector.tcp.config.ServerTransportConfig">
    <property name="tcpConnector" ref="tcpConnector" />
    <property name="proxy" ref="proxy" />
    <property name="notify" ref="notify" />
    <property name="ingressConnectionMonitor" ref="ingressConnectionMonitor" />
    <property name="gzip" value="true" />
    <property name="login" value="false" />
  </bean>
  <bean id="tcpConnector" class="com.gateway.connector.tcp.TcpConnector"
      init-method="init" destroy-method="destroy">
    <property name="tcpSessionManager" ref="tcpSessionManager" />
  </bean>
  <bean id="topicManager" class="com.gateway.invoke.TopicManager" />
  <bean id="notify" class="com.gateway.notify.NotifyProxy">
    <property name="tcpConnector" ref="tcpConnector" />
    <property name="topicManager" ref="topicManager" />
  </bean>
</beans>
EOF

write_file "${DEPLOY_ROOT}/control/overrides/LoginSvr/config/DBPoolConfig.ini" <<EOF
####################DBPool Cinfig###############[Begin]###
[DBPOOL]
DBPOOL.DBCount=1
DBPOOL.LogLevel=0
DBPOOL.LogPath=./log/DBPool.log

DBPOOL.DBSourceName_0=ClickHouse1
DBPOOL.DBDriver_0=com.clickhouse.jdbc.ClickHouseDriver
DBPOOL.DBUrl_0=${CLICKHOUSE_JDBC_URL}
DBPOOL.DBUsername_0=${CLICKHOUSE_JDBC_USERNAME}
DBPOOL.DBPasswd_0=${CLICKHOUSE_JDBC_PASSWORD}
DBPOOL.DBCheckSql_0=select 1
DBPOOL.DBIsEncrypt_0=false
DBPOOL.DBMaxCount_0=10
DBPOOL.DBMinCount_0=5
DBPOOL.DBConnOutTime_0=1000
DBPOOL.DBConnCheckNumber_0=1000
DBPOOL.DBStrategy_0=false

CLICKHOUSE.DBCount=1
CLICKHOUSE.DBSourceName_0=ClickHouse1
CLICKHOUSE.DBUrl_0=${CLICKHOUSE_JDBC_URL}
CLICKHOUSE.DBUsername_0=${CLICKHOUSE_JDBC_USERNAME}
CLICKHOUSE.DBPasswd_0=${CLICKHOUSE_JDBC_PASSWORD}
CLICKHOUSE.DBIsEncrypt_0=false
CLICKHOUSE.DBMaxCount_0=50
CLICKHOUSE.DBMinCount_0=5
CLICKHOUSE.DBConnOutTime_0=1000
CLICKHOUSE.DBAsyncInsert_0=1
CLICKHOUSE.DBAsyncInsertMaxInternet_0=2000
EOF

write_file "${DEPLOY_ROOT}/control/overrides/QuantSvr/config/application.properties" <<EOF
serverKey=SERVER.QuantSvr
log4j.file=./config/log4j.ini
log4j.thread=1
log4j.writeTime=true
log4j.async=true

apsServerKey=SERVER.APSSvr
indServerKey=SERVER.INDSvr
mdServerKey=SERVER.MDSvr
[GW]
GWHost=127.0.0.1
GWPort=${APSSVR_GW_PORT}
GWUserName=qe
GWPassword=123456
GWProtocal=1

beginRunTime=00:01:00
endRunTime=12:00:00

symbolList=TRXUSDT|ETHUSDT|SOLUSDT|LINKUSDT|XRPUSDT|DOGEUSDT|ADAUSDT|BNBUSDT|BTCUSDT
symbolValue=500

stopLossPrice1=0.008
takeProfitPrice1=0.004

stopLossPrice2=0.008
takeProfitPrice2=0.007

stopLossPrice3=0.01
takeProfitPrice3=0.015

check2Kline=false
checkPosotionKline=18
checkKlineBP=0.03
text=5m
checkPNL=false
checkTakerPNL=false

checkMaxPositionCount=5
checkMaxPositionValue=5

queryKlineCount=100
type=1

schedule.Config=./config/quartz.properties

downLoadTradeCron=0 59 23 * * ?

downLoadTradePath=../../data/QuantSvr/
dailyReviewCron=0 10 0 * * ?
dailyReviewCandidateGenerateEnabled=true
dailyReviewCandidateProvider=deepseek
dailyReviewPath=../../data/review/

enableBot=${QUANTSVR_ENABLE_BOT}
botConfigs[0].botToken=${QUANTSVR_BOT_TOKEN}
botConfigs[0].botUserName=${QUANTSVR_BOT_USERNAME}
botConfigs[0].botStartPic=./config/welcome.gif
botConfigs[0].botStartPicText=<b>\u6211\u4EEC\u5F00\u59CB\u5427</b>\n\u8BF7\u70B9\u51FB\u4E0B\u53D1\u5F00\u59CB\u4EA4\u6613
botConfigs[0].botStartUrlText=\u5F00\u59CB\u4EA4\u6613
botConfigs[0].botStartUrl=https://rubydex.com/en/trade/BTCUSDT
botConfigs[0].botEnableDC=false

botGroupId=${QUANTSVR_BOT_GROUP_ID}

adminList=${QUANTSVR_BOT_ADMIN_LIST}

strategy=com.app.dc.quant.strategy.TeleStrategy
strategyBot=com.app.dc.service.tele.TeleBotImplHandler
venueTypeGW=BNFutures

dbType=clickhouse
dbpool.cfg=../../control/DBPoolConfig.ini
clickhouse.default=ClickHouse1
clickhouse.batchSize=10
clickhouse.batchPeriod=5000
EOF

write_file "${DEPLOY_ROOT}/control/overrides/INDSvr/config/application.properties" <<EOF
serverKey=SERVER.INDSvr
mdServerKey=SERVER.MDSvr
apsServerKey=SERVER.APSSvr
quantServerKey=SERVER.QuantSvr
textList=15m
kline.supported.texts=15m
kline.default.text=15m
initial.kline.backfill.intervals=15m,1h,1d
symbolList=TRXUSDT|ETHUSDT|SOLUSDT|LINKUSDT|XRPUSDT|DOGEUSDT|ADAUSDT|BNBUSDT|BTCUSDT|UNIUSDT
queryKlineCount=50
queryKlineCount1d=400

log4j.file=./config/log4j.ini
log4j.thread=1
log4j.writeTime=true
log4j.async=true

storePath=../../data/INDSvr/ind

dbpool.cfg=../../control/DBPoolConfig.ini
dbType=clickhouse
clickhouse.default=ClickHouse1

strategy.runtime.jar.enabled=true
strategy.runtime.load.enabled=true
strategy.runtime.load.cron=0 */1 * * * ?
strategy.runtime.executionText=15m
strategy.runtime.fallbackCandidates.enabled=false
strategy.runtime.selectionRefreshOnMissing.enabled=true
strategy.runtime.selectionRefreshOnMissing.cooldownMs=300000
strategy.selection.defaults=range=binanceRange,trend=binanceTrend,channel=binanceChannel
strategy.selection.backend=clickhouse
deepseek.api.key=${INDSVR_DEEPSEEK_API_KEY}
strategy.generate.provider=deepseek
strategy.generate.rootDir=../../data/INDSvr/strategy
workbench.strategy.backup.dir=/srv/dc/data/indsvr/backup
strategy.generate.async.default=true
strategy.generate.async.parallelism=2
strategy.generate.async.queueCapacity=32
strategy.generate.async.pollCron=0/3 * * * * ?
strategy.generate.async.batchSize=10
strategy.generate.async.threadNamePrefix=strategy-generate-async-
strategy.generate.async.staleMinutes=30
strategy.generation.task.table=dc.strategy_generation_task
strategy.source.norm.table=dc.strategy_source_norm
strategy.candidate.table=dc.strategy_candidate
strategy.backtest.task.table=dc.strategy_backtest_task
strategy.generate.fitWindowDays=120
strategy.generate.validateWindowDays=30
strategy.generate.forwardWindowDays=14
strategy.generate.backtestPriority=5
strategy.review.evolution.reanalysis.enabled=true
strategy.review.evolution.reanalysis.threadNamePrefix=strategy-review-evolution-
strategy.live.upgrade.auto.enabled=true
strategy.live.upgrade.auto.cron=0 20 */2 * * ?
strategy.live.upgrade.auto.limit=6
strategy.live.upgrade.auto.retryCooldownHours=12
strategy.live.upgrade.auto.maxAttemptsPerVersion=2

signalCron=0 0/15 * * * ?
deepSeekJobSignalCron=0 5 0 * * ?
chatGPTAnalysisEnabled=false
chatGPTAnalysisCron=0 10 8,20 * * ?
chatGPTAnalysisSwitchAlgoEnabled=true
chatGPTAnalysisSwitchAlgoQuantId=
chatGPTAnalysisSwitchAlgoWhenStrategy=TREND
chatGPTAnalysisSwitchAlgoValue=AI
market.scene.analysis.enabled=true
market.scene.analysis.provider=deepseek
market.scene.analysis.prompt-version=deepseek_market_scene_v3
market.scene.analysis.cron=0 0 0/12 * * ?
market.scene.analysis.freshHours=12
market.scene.analysis.table=dc.deepseek_market_scene_analysis
scene.strategy.selection.enabled=true
scene.strategy.selection.provider=deepseek
scene.strategy.selection.prompt-version=deepseek_live_strategy_selection_v4
scene.strategy.selection.cron=0 5 */6 * * ?
scene.strategy.selection.max-candidates=30
scene.strategy.selection.allow-default-fallback=false

binanceStageGuardEnabled=true
binanceRangeAllowedStages=0,2,B
binanceChannelAllowedStages=1,2,3,4,A,B,C
binanceTrendAllowedStages=1,3,4,A,C

chatGPTSentimentCron=0 0 8,20 * * ?
strategy.generate.engine.default=full_java
strategy.generate.engine.legacyFallback=true
strategy.generate.engine.classifierEnabledWhenSceneEmpty=true
strategy.generate.engine.sceneClassifierMinConfidence=0.75
strategy.generate.engine.promptVersion=spec_v1
strategy.generate.engine.templateVersion=scene_tpl_v1
strategy.generate.legacy.promptVersion=legacy_java_v1
strategy.generate.scene.classifier.prompt.version=scene_classifier_v1
EOF

write_file "${DEPLOY_ROOT}/control/overrides/APSSvr/config/application.properties" <<EOF
serverKey=SERVER.APSSvr
log4j.file=./config/log4j.ini
log4j.thread=1
log4j.writeTime=true
log4j.async=true

[BNFutures]
enableBinanceFlag=true

enableBookTickerFlag=false

enableSymbolTickerFlag=true

enableMarkPriceFlag=false

enableUserDataFlag=${APSSVR_ENABLE_USER_DATA}

enableKlineFlag=false
text=5m
limitQps=100
apiUrl=
#https://testnet.binancefuture.com
wssUrl=
#wss://stream.binancefuture.com/ws

[BirdEye]
enableJupFlag=false
BirdEyeEnableFlag=false
BirdEyeApiUrl=wss://public-api.birdeye.so/socket/solana?x-api-key=%s
BirdEyeApiKey=

[BNSpot]
BNSpotEnableFlag=false
BNSpotApiUrl=
#https://testnet.binance.vision
BNSpotWssUrl=
#wss://stream.testnet.binance.vision

dbpool.cfg=./config/DBPoolConfig.ini
dbpool.default=MYSQL0

apiKey=
secretKey=

binanceSymbolList=btcusdt|ethusdt
binanceSymbolAliasList=btcusdt|ethusdt
schedule.Config=./config/quartz.properties

storePath=../../data/APSSvr/
sleepTime=0
EOF

echo "Generated sensitive service config overrides under ${DEPLOY_ROOT}/control/overrides."
