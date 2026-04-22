# Architecture

## Scope

`dc-quant-deploy` packages the DC runtime as a single-host Docker Compose deployment.

Service scope:

- `zookeeper`
- `GW`
- `mdsvr`
- `apssvr`
- `quantsvr`
- `indsvr`
- `simsvr`
- `batchsvr`
- `web`
- `clickhouse`

## Service Ownership

- `GW` is the public service name. The Docker Compose service key is `gateway` for compatibility with existing scripts.
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
- `ghcr.io/skt-walter/simsvr:${SIMSVR_TAG}`
- `ghcr.io/bliplink/batchsvr:${BATCHSVR_TAG}`
- `ghcr.io/skt-walter/web:${WEB_TAG}`
- `clickhouse/clickhouse-server:${CLICKHOUSE_IMAGE_TAG}`

## Dependency Shape

- `zookeeper` provides the registry endpoint
- `clickhouse` provides persistent data storage
- all Java services depend on both `zookeeper` and `clickhouse`
- `web` depends on `GW`

## Runtime Mount Contract

Java services keep the existing internal runtime layout:

- `${DEPLOY_ROOT}/control -> /srv/dc/control`
- `${DEPLOY_ROOT}/data -> /srv/dc/data`
- `${DEPLOY_ROOT}/log -> /srv/dc/log`

The host runtime root should only need these top-level directories after initialization:

- `${DEPLOY_ROOT}/control`
- `${DEPLOY_ROOT}/data`
- `${DEPLOY_ROOT}/log`

ZooKeeper uses image-bundled config and persists only runtime data on the host:

- `${DEPLOY_ROOT}/data/zookeeper -> /opt/zookeeper/data`
- `${DEPLOY_ROOT}/log -> /opt/zookeeper/runtime/log`

ClickHouse persists data under:

- `${DEPLOY_ROOT}/data/clickhouse`
- `${DEPLOY_ROOT}/log/clickhouse`

Optional runtime config overrides live under:

- `${DEPLOY_ROOT}/control/overrides/<Service>/config/<file>`

Only existing override files are mounted. Missing files keep the image-bundled defaults.
