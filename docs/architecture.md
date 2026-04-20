# Architecture

## Scope

`dc-quant-deploy` packages the DC runtime as a single-host Docker Compose deployment.

Service scope:

- `zookeeper`
- `gateway` (`GW`)
- `mdsvr`
- `apssvr`
- `quantsvr`
- `indsvr`
- `simsvr`
- `batchsvr`
- `web`
- `clickhouse`

## Service Ownership

- `GW = gateway`
- `quantsvr` owns runtime trading and external signal handling
- `indsvr` owns generation and strategy candidate lifecycle
- `simsvr` owns backtest and optimization execution
- `batchsvr` owns scheduled reports and rollups
- `clickhouse` is the only database
- `zookeeper` is the registry backbone

## Image Map

- `ghcr.io/bliplink/zookeeper:${ZOOKEEPER_TAG}`
- `ghcr.io/bliplink/gw:${GW_TAG}`
- `ghcr.io/bliplink/mdsvr:${MDSVR_TAG}`
- `ghcr.io/bliplink/apssvr:${APSSVR_TAG}`
- `ghcr.io/bliplink/quantsvr:${QUANTSVR_TAG}`
- `ghcr.io/bliplink/indsvr:${INDSVR_TAG}`
- `ghcr.io/SKT-Walter/simsvr:${SIMSVR_TAG}`
- `ghcr.io/bliplink/batchsvr:${BATCHSVR_TAG}`
- `ghcr.io/SKT-Walter/web:${WEB_TAG}`
- `clickhouse/clickhouse-server:${CLICKHOUSE_IMAGE_TAG}`

## Dependency Shape

- `zookeeper` provides the registry endpoint
- `clickhouse` provides persistent data storage
- all Java services depend on both `zookeeper` and `clickhouse`
- `web` depends on `gateway`

## Runtime Mount Contract

Java services keep the existing internal runtime layout:

- `${DEPLOY_ROOT}/control -> /srv/dc/control`
- `${DEPLOY_ROOT}/data -> /srv/dc/data`
- `${DEPLOY_ROOT}/log -> /srv/dc/log`

ZooKeeper reads its own runtime config and data directly:

- `${DEPLOY_ROOT}/tpc/zookeeper/conf/zoo.cfg`
- `${DEPLOY_ROOT}/tpc/zookeeper/conf/jaas.conf`
- `${DEPLOY_ROOT}/tpc/zookeeper/data`

ClickHouse persists data under:

- `${DEPLOY_ROOT}/clickhouse/data`
- `${DEPLOY_ROOT}/clickhouse/log`
