#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${1:-${ROOT_DIR}/.env.prod}"

require_file() {
  [[ -f "$1" ]] || {
    echo "Missing required file: $1" >&2
    exit 1
  }
}

load_env() {
  require_file "${ENV_FILE}"
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
QUANTSVR_BOT_GROUP_ID="${QUANTSVR_BOT_GROUP_ID:-}"
QUANTSVR_BOT_ADMIN_LIST="${QUANTSVR_BOT_ADMIN_LIST:-}"

INDSVR_DEEPSEEK_API_KEY="${INDSVR_DEEPSEEK_API_KEY:-}"

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
GWPort=30035
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
textList=15m|30m|1d
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
strategy.selection.defaults=range=binanceRange,trend=binanceTrend,channel=binanceChannel
strategy.selection.backend=clickhouse
deepseek.api.key=${INDSVR_DEEPSEEK_API_KEY}
strategy.generate.provider=deepseek
strategy.generate.rootDir=../../data/INDSvr/strategy
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
market.scene.analysis.prompt-version=deepseek_market_scene_v1
market.scene.analysis.cron=0 0 */12 * * ?
market.scene.analysis.symbols=BTCUSDT,ETHUSDT
market.scene.analysis.table=dc.deepseek_market_scene_analysis
scene.strategy.selection.enabled=true
scene.strategy.selection.provider=deepseek
scene.strategy.selection.prompt-version=deepseek_live_strategy_selection_v3
scene.strategy.selection.cron=0 5 */12 * * ?
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

enableUserDataFlag=false

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
