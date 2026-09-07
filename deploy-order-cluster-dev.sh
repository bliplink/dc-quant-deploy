#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/compose.order-cluster-dev.yaml"
PROJECT_NAME="dc-saas-order-cluster-dev"
ORDER_CLUSTER_DEV_ROOT="${ORDER_CLUSTER_DEV_ROOT:-/data/dc-saas-order-cluster-dev}"
SAAS_CONTROL_ROOT="${SAAS_CONTROL_ROOT:-/data/dc-saas-runtime/control}"
ZOOKEEPER_CONTAINER="${ZOOKEEPER_CONTAINER:-dc-saas-cluster-zookeeper}"
ZOOKEEPER_ENDPOINT="${ZOOKEEPER_ENDPOINT:-127.0.0.1:32182}"

log() { printf '[order-cluster-dev] %s\n' "$*"; }
die() { printf '[order-cluster-dev] ERROR: %s\n' "$*" >&2; exit 1; }

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

[[ -n "${ORDERSVR_CLUSTER_DEV_IMAGE:-}" ]] || die 'ORDERSVR_CLUSTER_DEV_IMAGE is required'
[[ -n "${GW_CLUSTER_DEV_IMAGE:-}" ]] || die 'GW_CLUSTER_DEV_IMAGE is required'
require_order_image "${ORDERSVR_CLUSTER_DEV_IMAGE}"
require_gw_image "${GW_CLUSTER_DEV_IMAGE}"
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
ProtoVersion=1

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
Partition.OrderSvr.Fields=location,marketIndicator,securityID
Partition.OrderSvr.Alias.location=Location
Partition.OrderSvr.Alias.marketIndicator=MarketIndicator
Partition.OrderSvr.Alias.securityID=SecurityID,securityId
Partition.OrderSvr.Root=/dc/cluster/ordersvr-dev/partitions
Partition.OrderSvr.EnforceFence=true
Partition.OrderSvrA.Count=256
Partition.OrderSvrA.Root=/dc/cluster/ordersvr-dev/partitions
Partition.OrderSvrA.EnforceFence=true
Partition.OrderSvrB.Count=256
Partition.OrderSvrB.Root=/dc/cluster/ordersvr-dev/partitions
Partition.OrderSvrB.EnforceFence=true
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
order.cluster.state.enabled=false
order.cluster.state.required=false
order.cluster.state.replication.required=false
order.cluster.commit.enabled=false
order.cluster.commit.required=false
order.cluster.snapshot.enabled=false
order.cluster.snapshotDir=../../data/${node}/snapshot
order.cluster.replication.enabled=true
order.cluster.replication.required=true
order.cluster.replication.bindHost=127.0.0.1
order.cluster.replication.port=${replication_port}
order.cluster.replication.requestTimeoutMs=3000
order.cluster.replication.catchupBatchRecords=256
order.cluster.replication.peers=OrderSvrA=127.0.0.1:19111,OrderSvrB=127.0.0.1:19112
order.cluster.defaultMarketIndicator=4
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
  "${ORDER_CLUSTER_DEV_ROOT}/nodes/OrderSvrA" "${ORDER_CLUSTER_DEV_ROOT}/nodes/OrderSvrB" "${ORDER_CLUSTER_DEV_ROOT}/gateway" "${ORDER_CLUSTER_DEV_ROOT}/evidence"
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

log 'Seeding isolated partition assignments in the cluster development ZooKeeper'
cat <<'EOF' | sudo docker exec -i \
  "${ZOOKEEPER_CONTAINER}" zkCli.sh -server "${ZOOKEEPER_ENDPOINT}" >/tmp/order-cluster-dev-zk-seed.log 2>&1
create /dc x
create /dc/cluster x
create /dc/cluster/ordersvr-dev x
create /dc/cluster/ordersvr-dev/partitions x
create /dc/cluster/ordersvr-dev/partitions/P027 {"partitionId":"P027","epoch":1,"primary":"OrderSvrA","replica":"OrderSvrB","state":"READY"}
set /dc/cluster/ordersvr-dev/partitions/P027 {"partitionId":"P027","epoch":1,"primary":"OrderSvrA","replica":"OrderSvrB","state":"READY"}
create /dc/cluster/ordersvr-dev/partitions/P132 {"partitionId":"P132","epoch":1,"primary":"OrderSvrB","replica":"OrderSvrA","state":"READY"}
set /dc/cluster/ordersvr-dev/partitions/P132 {"partitionId":"P132","epoch":1,"primary":"OrderSvrB","replica":"OrderSvrA","state":"READY"}
quit
EOF

log 'Starting isolated OrderSvr A/B and GW containers'
sudo -E docker compose -p "${PROJECT_NAME}" -f "${COMPOSE_FILE}" up -d
wait_port 33336 OrderSvrA
wait_port 33337 OrderSvrB
wait_port 19111 'OrderSvrA replication'
wait_port 19112 'OrderSvrB replication'
wait_port 33302 'cluster development GW HTTP'

log "READY: GW=http://127.0.0.1:33302, Common=${order_common_revision}, SHA256=${order_common_hash}"
log "Run tests with: sudo -E ${SCRIPT_DIR}/tests/run-order-cluster-ab-host.sh"
