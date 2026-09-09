#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/compose.order-cluster-dev.yaml"
PROJECT_NAME="dc-saas-order-cluster-dev"
ORDER_CLUSTER_DEV_ROOT="${ORDER_CLUSTER_DEV_ROOT:-/data/dc-saas-order-cluster-dev}"
SAAS_CONTROL_ROOT="${SAAS_CONTROL_ROOT:-/data/dc-saas-runtime/control}"
DEPLOY_STATE_DIR="${ORDER_CLUSTER_DEV_ROOT}/deploy-state"
LAST_SUCCESSFUL_MANIFEST="${DEPLOY_STATE_DIR}/last-successful.env"
ROLLBACK_MANIFEST="${DEPLOY_STATE_DIR}/rollback.env"
ZOOKEEPER_CONTAINER="${ZOOKEEPER_CONTAINER:-dc-saas-cluster-zookeeper}"
ZOOKEEPER_ENDPOINT="${ZOOKEEPER_ENDPOINT:-127.0.0.1:32182}"
ORDER_CLUSTER_REPLICATION_CONSISTENCY_MODE="${ORDER_CLUSTER_REPLICATION_CONSISTENCY_MODE:-SYNC_PER_RECORD}"
ORDER_CLUSTER_REPLICATION_BATCH_MAX_RECORDS="${ORDER_CLUSTER_REPLICATION_BATCH_MAX_RECORDS:-64}"
ORDER_CLUSTER_REPLICATION_BATCH_MAX_WAIT_MICROS="${ORDER_CLUSTER_REPLICATION_BATCH_MAX_WAIT_MICROS:-1000}"
ORDER_CLUSTER_REPLICATION_BATCH_THREADS="${ORDER_CLUSTER_REPLICATION_BATCH_THREADS:-2}"
ORDER_CLUSTER_REPLICATION_ASYNC_RETRY_MILLIS="${ORDER_CLUSTER_REPLICATION_ASYNC_RETRY_MILLIS:-100}"
ORDER_CLUSTER_REPLICATION_ASYNC_MAX_PENDING_RECORDS="${ORDER_CLUSTER_REPLICATION_ASYNC_MAX_PENDING_RECORDS:-8192}"

log() { printf '[order-cluster-dev] %s\n' "$*"; }
die() { printf '[order-cluster-dev] ERROR: %s\n' "$*" >&2; exit 1; }

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

require_order_image() {
  local image="$1"
  [[ "${image}" =~ ^ghcr\.io/bliplink/ordersvr:cluster-dev-[0-9a-f]{7,40}$ ]] ||
    die "refusing non-immutable OrderSvr image: ${image}"
}

require_gw_image() {
  local image="$1"
  [[ "${image}" =~ ^ghcr\.io/bliplink/ordersvr:gw-cluster-dev-[0-9a-f]{7,40}$ ]] ||
    die "refusing non-immutable GW development image: ${image}"
}

image_label() {
  sudo docker image inspect "$1" --format "{{ index .Config.Labels \"$2\" }}"
}

embedded_common_hash() {
  local image="$1" service="$2"
  sudo docker run --rm --entrypoint sh "${image}" -c \
    "set -- /srv/dc/dc/${service}/lib/com.app.common-*.jar; [ \"\$#\" -eq 1 ] && sha256sum \"\$1\" | awk '{print \$1}'"
}

manifest_value() {
  local file="$1" key="$2"
  sudo awk -F= -v key="${key}" '$1 == key { sub(/^[^=]*=/, ""); print; exit }' "${file}"
}

wait_port() {
  local port="$1" name="$2" deadline=$((SECONDS + 90))
  while (( SECONDS < deadline )); do
    if (exec 3<>"/dev/tcp/127.0.0.1/${port}") 2>/dev/null; then
      exec 3>&-
      return 0
    fi
    sleep 1
  done
  die "${name} did not listen on 127.0.0.1:${port}"
}

wait_healthy() {
  local container="$1" deadline=$((SECONDS + 150)) status
  while (( SECONDS < deadline )); do
    status="$(sudo docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' \
      "${container}" 2>/dev/null || true)"
    if [[ "${status}" == healthy ]]; then
      return 0
    fi
    if [[ "${status}" == unhealthy ]]; then
      sudo docker inspect -f '{{range .State.Health.Log}}{{println .Output}}{{end}}' "${container}" >&2 || true
      die "${container} became unhealthy"
    fi
    sleep 2
  done
  die "${container} did not become healthy before the startup deadline"
}

ensure_znode() {
  local path="$1" data="$2"
  if sudo docker exec "${ZOOKEEPER_CONTAINER}" zkCli.sh -server "${ZOOKEEPER_ENDPOINT}" \
    get "${path}" >/dev/null 2>&1; then
    return 0
  fi
  sudo docker exec "${ZOOKEEPER_CONTAINER}" zkCli.sh -server "${ZOOKEEPER_ENDPOINT}" \
    create "${path}" "${data}" >>/tmp/order-cluster-dev-zk-seed.log 2>&1
}

[[ -n "${ORDERSVR_CLUSTER_DEV_IMAGE:-}" ]] || die 'ORDERSVR_CLUSTER_DEV_IMAGE is required'
[[ -n "${GW_CLUSTER_DEV_IMAGE:-}" ]] || die 'GW_CLUSTER_DEV_IMAGE is required'
require_order_image "${ORDERSVR_CLUSTER_DEV_IMAGE}"
require_gw_image "${GW_CLUSTER_DEV_IMAGE}"
previous_order_image=""
previous_gw_image=""
if sudo test -r "${LAST_SUCCESSFUL_MANIFEST}"; then
  previous_order_image="$(manifest_value "${LAST_SUCCESSFUL_MANIFEST}" ORDERSVR_CLUSTER_DEV_IMAGE)"
  previous_gw_image="$(manifest_value "${LAST_SUCCESSFUL_MANIFEST}" GW_CLUSTER_DEV_IMAGE)"
  require_order_image "${previous_order_image}"
  require_gw_image "${previous_gw_image}"
fi
[[ -f "${COMPOSE_FILE}" ]] || die "missing ${COMPOSE_FILE}"
sudo test -r "${SAAS_CONTROL_ROOT}/dc.dat" || die 'existing SaaS dc.dat is unavailable'
sudo test -r "${SAAS_CONTROL_ROOT}/jaas.ini" || die 'existing SaaS jaas.ini is unavailable'

log 'Pulling immutable cluster development images'
sudo docker pull "${ORDERSVR_CLUSTER_DEV_IMAGE}"
sudo docker pull "${GW_CLUSTER_DEV_IMAGE}"

order_common_revision="$(image_label "${ORDERSVR_CLUSTER_DEV_IMAGE}" dc.common.revision)"
gw_common_revision="$(image_label "${GW_CLUSTER_DEV_IMAGE}" dc.common.revision)"
order_common_hash="$(image_label "${ORDERSVR_CLUSTER_DEV_IMAGE}" dc.common.jar.sha256)"
gw_common_hash="$(image_label "${GW_CLUSTER_DEV_IMAGE}" dc.common.jar.sha256)"
[[ -n "${order_common_revision}" && "${order_common_revision}" != unknown ]] || die 'OrderSvr Common revision label is missing'
[[ "${order_common_revision}" == "${gw_common_revision}" ]] || die 'OrderSvr/GW Common revisions differ'
[[ -n "${order_common_hash}" && "${order_common_hash}" != unknown ]] || die 'OrderSvr Common SHA-256 label is missing'
[[ "${order_common_hash}" == "${gw_common_hash}" ]] || die 'OrderSvr/GW Common SHA-256 labels differ'
[[ "$(embedded_common_hash "${ORDERSVR_CLUSTER_DEV_IMAGE}" OrderSvr)" == "${order_common_hash}" ]] || die 'OrderSvr embedded Common hash differs from label'
[[ "$(embedded_common_hash "${GW_CLUSTER_DEV_IMAGE}" GW)" == "${gw_common_hash}" ]] || die 'GW embedded Common hash differs from label'

export ORDER_CLUSTER_DEV_ROOT ORDERSVR_CLUSTER_DEV_IMAGE GW_CLUSTER_DEV_IMAGE
sudo -E docker compose -p "${PROJECT_NAME}" -f "${COMPOSE_FILE}" down --remove-orphans >/dev/null 2>&1 || true

for port in 32182 32889 33889 33300 33301 33302 33336 33337 19111 19112; do
  if sudo ss -ltnH "sport = :${port}" | grep -q .; then
    die "TCP port ${port} is already in use"
  fi
done

tmp_root="$(mktemp -d)"
trap 'rm -rf -- "${tmp_root}"' EXIT
mkdir -p "${tmp_root}/control" "${tmp_root}/nodes/OrderSvrA" "${tmp_root}/nodes/OrderSvrB" "${tmp_root}/gateway"

cat >"${tmp_root}/control/ATSConfig.ini" <<EOF
REGISTER.ServerList=REGISTER.Svr1
REGISTER.Svr1.Name=REGISTER1
REGISTER.Svr1.Host=${ZOOKEEPER_ENDPOINT}
NetType=dps
ProtoVersion=2

SERVER.OrderSvr.Name=OrderSvr
SERVER.OrderSvr.Host=127.0.0.1:33999
SERVER.OrderSvr.RegType=0
SERVER.OrderSvr.RegisterEnable=1
SERVER.OrderSvr.LBFactor=1
SERVER.OrderSvr.ServiceName=OrderSvr
SERVER.OrderSvr.RegisterServerList=REGISTER.Svr1

SERVER.OrderSvrA.Name=OrderSvrA
SERVER.OrderSvrA.Host=127.0.0.1:33336
SERVER.OrderSvrA.RegType=0
SERVER.OrderSvrA.RegisterEnable=1
SERVER.OrderSvrA.LBFactor=1
SERVER.OrderSvrA.ServiceName=OrderSvrA
SERVER.OrderSvrA.RegisterServerList=REGISTER.Svr1

SERVER.OrderSvrB.Name=OrderSvrB
SERVER.OrderSvrB.Host=127.0.0.1:33337
SERVER.OrderSvrB.RegType=0
SERVER.OrderSvrB.RegisterEnable=1
SERVER.OrderSvrB.LBFactor=1
SERVER.OrderSvrB.ServiceName=OrderSvrB
SERVER.OrderSvrB.RegisterServerList=REGISTER.Svr1

SERVER.LoginSvr.Name=LoginSvr
SERVER.LoginSvr.Host=127.0.0.1:33991
SERVER.LoginSvr.RegType=2
SERVER.LoginSvr.RegisterEnable=1
SERVER.LoginSvr.LBFactor=1
SERVER.LoginSvr.ServiceName=LoginSvrClusterDevMissing
SERVER.LoginSvr.RegisterServerList=REGISTER.Svr1

SERVER.AdminSvr.Name=AdminSvr
SERVER.AdminSvr.Host=127.0.0.1:33992
SERVER.AdminSvr.RegType=2
SERVER.AdminSvr.RegisterEnable=1
SERVER.AdminSvr.LBFactor=1
SERVER.AdminSvr.ServiceName=AdminSvrClusterDevMissing
SERVER.AdminSvr.RegisterServerList=REGISTER.Svr1

SERVER.TradeSvr.Name=TradeSvr
SERVER.TradeSvr.Host=127.0.0.1:33993
SERVER.TradeSvr.RegType=2
SERVER.TradeSvr.RegisterEnable=1
SERVER.TradeSvr.LBFactor=1
SERVER.TradeSvr.ServiceName=TradeSvrClusterDevMissing
SERVER.TradeSvr.RegisterServerList=REGISTER.Svr1

LBConfig.OrderSvr=Partition
Cluster.Enabled=true
Cluster.OrderSvr.Enabled=true
Cluster.OrderSvrA.Enabled=true
Cluster.OrderSvrB.Enabled=true
Partition.OrderSvr.Count=256
Partition.OrderSvr.Root=/dc/cluster/ordersvr-dev/partitions
Partition.OrderSvr.EnforceFence=true
Partition.OrderSvrA.Count=256
Partition.OrderSvrA.Root=/dc/cluster/ordersvr-dev/partitions
Partition.OrderSvrA.EnforceFence=true
Partition.OrderSvrA.EnforceReadiness=true
Partition.OrderSvrB.Count=256
Partition.OrderSvrB.Root=/dc/cluster/ordersvr-dev/partitions
Partition.OrderSvrB.EnforceFence=true
Partition.OrderSvrB.EnforceReadiness=true
EOF

write_order_config() {
  local node="$1" replication_port="$2"
  cat >"${tmp_root}/nodes/${node}/application.properties" <<EOF
dbType=rockdb
execOrderType=default
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
order.cluster.lifecycle.enabled=true
order.cluster.lifecycle.bootstrap.enabled=true
order.cluster.lifecycle.pollMillis=1000
order.cluster.lifecycle.retryMillis=5000
order.cluster.perfProbe.enabled=true
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
order.cluster.replication.peers=OrderSvrA=127.0.0.1:19111,OrderSvrB=127.0.0.1:19112
order.cluster.defaultMarketIndicator=4
order.tenantSymbolRules.enabled=false
enableMarketPrice=false
enableSaveDBDemo=false
enableDepthDiff=false
enableFullOrderBookOnChange=false
order.selfTradePreventionMode=CANCEL_TAKER
enablePerfStats=false
log4j.file=./config/log4j.ini
log4j.thread=1
log4j.writeTime=true
log4j.async=false
EOF
}
write_order_config OrderSvrA 19111
write_order_config OrderSvrB 19112

write_order_log4j() {
  local node="$1"
  cat >"${tmp_root}/nodes/${node}/log4j.ini" <<EOF
log4j.rootLogger=INFO,file,stdout
log4j.appender.file=org.apache.log4j.DailyRollingFileAppender
log4j.appender.file.File=../../log/${node}.log
log4j.appender.file.Append=true
log4j.appender.file.layout=org.apache.log4j.PatternLayout
log4j.appender.file.layout.ConversionPattern=%d{yyyy/MM/dd HH:mm:ss.SSS} %p %m (%C{1}:%L)%n
log4j.appender.stdout=org.apache.log4j.ConsoleAppender
log4j.appender.stdout.Target=System.out
log4j.appender.stdout.layout=org.apache.log4j.PatternLayout
log4j.appender.stdout.layout.ConversionPattern=%d{yyyy/MM/dd HH:mm:ss.SSS} %p %m (%C{1}:%L)%n
log4j.logger.com.app.dc.service.cluster.OrderClusterAdapter=DEBUG
EOF
}
write_order_log4j OrderSvrA
write_order_log4j OrderSvrB

cat >"${tmp_root}/gateway/spring-config.xml" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<beans xmlns="http://www.springframework.org/schema/beans" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://www.springframework.org/schema/beans http://www.springframework.org/schema/beans/spring-beans-3.0.xsd">
 <import resource="spring-tcp-server.xml"/>
 <import resource="spring-gw-client.xml"/>
</beans>
EOF
cat >"${tmp_root}/gateway/spring-gw-client.xml" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<beans xmlns="http://www.springframework.org/schema/beans" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://www.springframework.org/schema/beans http://www.springframework.org/schema/beans/spring-beans-3.0.xsd">
 <bean id="proxy" class="com.gateway.invoke.gw.GWProxy" init-method="init">
  <property name="topicManager" ref="topicManager"/><property name="notifyProxy" ref="notify"/><property name="tcpConnector" ref="tcpConnector"/>
  <property name="SessionService" value=""/><property name="RequestService" value="OrderSvr"/><property name="Subscribes"><map/></property>
  <property name="securityChecks"><list/></property><property name="filterTopics"><list/></property><property name="ApiKeyService" ref="apiKeyService"/>
 </bean>
 <bean id="apiKeyService" class="com.gateway.invoke.filter.apikey.ApiKeyService"/>
</beans>
EOF
cat >"${tmp_root}/gateway/spring-tcp-server.xml" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<beans xmlns="http://www.springframework.org/schema/beans" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://www.springframework.org/schema/beans http://www.springframework.org/schema/beans/spring-beans-4.3.xsd">
 <bean id="tcpServer" class="com.gateway.connector.tcp.server.TServer" init-method="init" destroy-method="shutdown"><property name="port" value="33300"/><property name="serverConfig" ref="serverConfig"/></bean>
 <bean id="webSocketServer" class="com.gateway.connector.tcp.server.WebSocketServer" init-method="init" destroy-method="shutdown"><property name="port" value="33301"/><property name="serverConfig" ref="webSocketServerConfig"/></bean>
 <bean id="httpServer" class="com.gateway.connector.tcp.server.HttpServer" init-method="init" destroy-method="shutdown"><property name="port" value="33302"/><property name="serverConfig" ref="serverConfig"/></bean>
 <bean id="tcpSessionManager" class="com.gateway.connector.tcp.TcpSessionManager"><property name="maxInactiveInterval" value="500"/><property name="topicManager" ref="topicManager"/><property name="sessionListeners"><list><ref bean="logSessionListener"/></list></property></bean>
 <bean id="logSessionListener" class="com.gateway.connector.api.listener.LogSessionListener"/><bean id="tcpSender" class="com.gateway.remoting.TcpSender"><property name="tcpConnector" ref="tcpConnector"/></bean>
 <bean id="serverConfig" class="com.gateway.connector.tcp.config.ServerTransportConfig"><property name="tcpConnector" ref="tcpConnector"/><property name="proxy" ref="proxy"/><property name="notify" ref="notify"/><property name="gzip" value="true"/><property name="login" value="false"/></bean>
 <bean id="webSocketServerConfig" class="com.gateway.connector.tcp.config.ServerTransportConfig"><property name="tcpConnector" ref="tcpConnector"/><property name="proxy" ref="proxy"/><property name="notify" ref="notify"/><property name="gzip" value="true"/><property name="login" value="false"/></bean>
 <bean id="tcpConnector" class="com.gateway.connector.tcp.TcpConnector" init-method="init" destroy-method="destroy"><property name="tcpSessionManager" ref="tcpSessionManager"/></bean>
 <bean id="topicManager" class="com.gateway.invoke.TopicManager"/><bean id="notify" class="com.gateway.notify.NotifyProxy"><property name="tcpConnector" ref="tcpConnector"/><property name="topicManager" ref="topicManager"/></bean>
</beans>
EOF

sudo install -d -m 0750 "${ORDER_CLUSTER_DEV_ROOT}/control" "${ORDER_CLUSTER_DEV_ROOT}/data" "${ORDER_CLUSTER_DEV_ROOT}/log" \
  "${ORDER_CLUSTER_DEV_ROOT}/zookeeper/data" "${ORDER_CLUSTER_DEV_ROOT}/zookeeper/datalog" "${ORDER_CLUSTER_DEV_ROOT}/zookeeper/logs" \
  "${ORDER_CLUSTER_DEV_ROOT}/nodes/OrderSvrA" "${ORDER_CLUSTER_DEV_ROOT}/nodes/OrderSvrB" "${ORDER_CLUSTER_DEV_ROOT}/gateway" \
  "${ORDER_CLUSTER_DEV_ROOT}/evidence" "${DEPLOY_STATE_DIR}"
sudo install -m 0600 "${SAAS_CONTROL_ROOT}/dc.dat" "${ORDER_CLUSTER_DEV_ROOT}/control/dc.dat"
sudo install -m 0600 "${SAAS_CONTROL_ROOT}/jaas.ini" "${ORDER_CLUSTER_DEV_ROOT}/control/jaas.ini"
sudo install -m 0644 "${tmp_root}/control/ATSConfig.ini" "${ORDER_CLUSTER_DEV_ROOT}/control/ATSConfig.ini"
sudo install -m 0644 "${tmp_root}/nodes/OrderSvrA/application.properties" "${ORDER_CLUSTER_DEV_ROOT}/nodes/OrderSvrA/application.properties"
sudo install -m 0644 "${tmp_root}/nodes/OrderSvrB/application.properties" "${ORDER_CLUSTER_DEV_ROOT}/nodes/OrderSvrB/application.properties"
sudo install -m 0644 "${tmp_root}/nodes/OrderSvrA/log4j.ini" "${ORDER_CLUSTER_DEV_ROOT}/nodes/OrderSvrA/log4j.ini"
sudo install -m 0644 "${tmp_root}/nodes/OrderSvrB/log4j.ini" "${ORDER_CLUSTER_DEV_ROOT}/nodes/OrderSvrB/log4j.ini"
sudo install -m 0644 "${tmp_root}/gateway/"*.xml "${ORDER_CLUSTER_DEV_ROOT}/gateway/"

log 'Starting the isolated cluster development ZooKeeper'
sudo -E docker compose -p "${PROJECT_NAME}" -f "${COMPOSE_FILE}" up -d zookeeper
wait_port 32182 'cluster development ZooKeeper'
wait_healthy "${ZOOKEEPER_CONTAINER}"

log 'Seeding isolated partition assignments in the cluster development ZooKeeper'
: >/tmp/order-cluster-dev-zk-seed.log
ensure_znode /MDTService x
ensure_znode /dc x
ensure_znode /dc/cluster x
ensure_znode /dc/cluster/ordersvr-dev x
ensure_znode /dc/cluster/ordersvr-dev/partitions x
# Existing assignments are deliberately read-only here. Reinstalling must never
# decrease a fencing epoch or silently overwrite a control-plane role change.
ensure_znode /dc/cluster/ordersvr-dev/partitions/P027 \
  '{"partitionId":"P027","epoch":1,"primary":"OrderSvrA","replica":"OrderSvrB","state":"READY"}'
ensure_znode /dc/cluster/ordersvr-dev/partitions/P132 \
  '{"partitionId":"P132","epoch":1,"primary":"OrderSvrB","replica":"OrderSvrA","state":"READY"}'

log 'Starting isolated OrderSvr A/B and GW containers'
sudo -E docker compose -p "${PROJECT_NAME}" -f "${COMPOSE_FILE}" up -d
wait_port 33336 OrderSvrA
wait_port 33337 OrderSvrB
wait_port 19111 'OrderSvrA replication'
wait_port 19112 'OrderSvrB replication'
wait_port 33302 'cluster development GW HTTP'
wait_healthy dc-saas-cluster-ordersvr-a
wait_healthy dc-saas-cluster-ordersvr-b
wait_healthy dc-saas-cluster-gateway

write_manifest() {
  local target="$1" order_image="$2" gw_image="$3"
  cat >"${tmp_root}/deployment.env" <<EOF
ORDERSVR_CLUSTER_DEV_IMAGE=${order_image}
GW_CLUSTER_DEV_IMAGE=${gw_image}
DEPLOYED_AT_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)
COMMON_REVISION=${order_common_revision}
COMMON_JAR_SHA256=${order_common_hash}
EOF
  sudo install -m 0640 "${tmp_root}/deployment.env" "${target}"
}

if [[ -n "${previous_order_image}" && -n "${previous_gw_image}" ]] &&
  [[ "${previous_order_image}" != "${ORDERSVR_CLUSTER_DEV_IMAGE}" ||
     "${previous_gw_image}" != "${GW_CLUSTER_DEV_IMAGE}" ]]; then
  sudo install -m 0640 "${LAST_SUCCESSFUL_MANIFEST}" "${ROLLBACK_MANIFEST}"
fi
write_manifest "${LAST_SUCCESSFUL_MANIFEST}" "${ORDERSVR_CLUSTER_DEV_IMAGE}" "${GW_CLUSTER_DEV_IMAGE}"

log "READY: GW=http://127.0.0.1:33302, Common=${order_common_revision}, SHA256=${order_common_hash}"
log "Run tests with: sudo -E ${SCRIPT_DIR}/tests/run-order-cluster-ab-host.sh"
log "Rollback with: ${SCRIPT_DIR}/rollback-order-cluster-dev.sh"
