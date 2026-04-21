# dc-quant-deploy

`dc-quant-deploy` is the open deployment repository for the DC quantitative trading stack.

Language:

- English: [README.md](./README.md)
- Simplified Chinese: [README.zh-CN.md](./README.zh-CN.md)

## Purpose

This repository provides a single-host Docker Compose deployment for:

- `zookeeper`
- `gateway` / `GW`
- `mdsvr`
- `apssvr`
- `quantsvr`
- `indsvr`
- `simsvr`
- `batchsvr`
- `web`
- `clickhouse`

Core contracts:

- Deployment shape: single-host Docker Compose.
- Database boundary: ClickHouse only. MySQL is not required.
- Release model: versioned container images.
- `GW = gateway`.
- After initialization, the runtime root only needs `control/`, `data/`, and `log/`.

This repository does not include real production secrets or real production `control.prod/`.

## Quick Start

For the complete installation, validation, and operations walkthrough, start with the [User Manual](./docs/user-manual.md).

Minimal path:

```bash
git clone https://github.com/bliplink/dc-quant-deploy.git
cd dc-quant-deploy
cp .env.standalone.example .env.prod
cp -a control.prod.example control.prod
vi .env.prod
vi control.prod/ATSConfig.ini
vi control.prod/DBPoolConfig.ini
vi control.prod/jaas.ini
cp /path/to/dc.dat control.prod/dc.dat
./deploy-standalone.sh
```

If ClickHouse already exists, use:

```bash
cp .env.external-clickhouse.example .env.prod
cp -a control.prod.example control.prod
vi .env.prod
vi control.prod/ATSConfig.ini
vi control.prod/DBPoolConfig.ini
vi control.prod/jaas.ini
cp /path/to/dc.dat control.prod/dc.dat
./deploy-with-external-clickhouse.sh
```

Check status after deployment:

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml ps
```

## Repository Layout

- [compose.yaml](./compose.yaml): main deployment topology.
- [.env.example](./.env.example): public deployment variables template.
- [.env.standalone.example](./.env.standalone.example): template for a new server with embedded ClickHouse.
- [.env.external-clickhouse.example](./.env.external-clickhouse.example): template for an existing ClickHouse deployment.
- [deploy.sh](./deploy.sh): one-command deployment entry.
- [deploy-standalone.sh](./deploy-standalone.sh): one-command deployment from scratch, including ClickHouse.
- [deploy-with-external-clickhouse.sh](./deploy-with-external-clickhouse.sh): one-command deployment with an existing ClickHouse.
- [validate.sh](./validate.sh): preflight validation.
- [rollback.sh](./rollback.sh): full rollback entry.
- [deploy-service.sh](./deploy-service.sh): one-service cutover entry.
- [rollback-service.sh](./rollback-service.sh): one-service rollback entry.
- [restart-service.sh](./restart-service.sh): restart exactly one containerized service.
- [control.template](./control.template): placeholder-based control templates.
- [control.prod.example](./control.prod.example): sanitized example control files.
- [clickhouse](./clickhouse): ClickHouse bootstrap SQL and helper scripts.
- [docs/user-manual.md](./docs/user-manual.md): full installation and operations manual.
- [docs/deployment-modes.md](./docs/deployment-modes.md): standalone vs existing-ClickHouse deployment modes.
- [docs/architecture.md](./docs/architecture.md): service and image map.
- [docs/database.md](./docs/database.md): ClickHouse initialization contract.
- [docs/runtime-overrides.md](./docs/runtime-overrides.md): optional config overrides and log level changes.
- [docs/release-flow.md](./docs/release-flow.md): image-based release flow.
- [docs/service-cutover.md](./docs/service-cutover.md): one-service-at-a-time production cutover.

## ClickHouse Modes

The repository supports two ClickHouse modes.

1. `embedded`
   Use this when you do not already have ClickHouse. Run `./deploy-standalone.sh`.
2. `external`
   Use this when ClickHouse already exists. Run `./deploy-with-external-clickhouse.sh`.

Configure `.env.prod`:

```dotenv
CLICKHOUSE_MODE=embedded
CLICKHOUSE_IMAGE_TAG=25.9.3.48
CLICKHOUSE_DB_NAME=dc
CLICKHOUSE_HOST=127.0.0.1
CLICKHOUSE_HTTP_PORT=8123
CLICKHOUSE_NATIVE_PORT=9000
CLICKHOUSE_USERNAME=default
CLICKHOUSE_PASSWORD=
```

For external ClickHouse, initialize manually when needed:

```bash
./clickhouse/apply-init.sh
```

Default initialization creates the database, tables, and views. Optional seed scripts are not executed automatically.

`deploy.sh` remains the shared lower-level entry. The two mode-specific scripts set the safe `CLICKHOUSE_MODE` value, back up `.env.prod`, and then call `deploy.sh`.

## Images

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

If GHCR authentication is required:

```bash
docker login ghcr.io
```

Then set:

```dotenv
REQUIRE_GHCR_LOGIN=true
```

## Secrets And Local Files

Do not commit these files or directories:

- `.env.prod`
- `control.prod/`
- `${DEPLOY_ROOT}/control`
- `${DEPLOY_ROOT}/data`
- `${DEPLOY_ROOT}/log`

`dc.dat` is a license file and belongs to the local deployment instance.

## Operations

Restart one service:

```bash
./restart-service.sh apssvr
```

Stop one service:

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml stop apssvr
```

Start one service:

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml up -d --no-deps apssvr
```

View logs:

```bash
docker logs dc-apssvr --tail 200
tail -n 100 ${DEPLOY_ROOT}/log/APSSvr.log
```

## Runtime Overrides

Image-bundled config is the default. Host files are mounted only when they exist under `${DEPLOY_ROOT}/control/overrides`.

Supported overrides:

- `GW/config/mcpTools.tsv`
- `GW/config/apiKeyList.csv`
- `GW/config/spring-gw-client.xml`
- `GW/config/log4j.ini`
- `MDSvr/config/log4j.ini`
- `APSSvr/config/log4j.ini`
- `QuantSvr/config/log4j.ini`
- `INDSvr/config/log4j.ini`
- `SIMSvr/config/log4j.ini`
- `BatchSvr/config/log4j.ini`

After adding a new override file, restart the target service once:

```bash
./restart-service.sh apssvr
```

## Documentation

- [User Manual](./docs/user-manual.md)
- [Deployment Modes](./docs/deployment-modes.md)
- [Architecture](./docs/architecture.md)
- [Database](./docs/database.md)
- [Runtime Overrides](./docs/runtime-overrides.md)
- [Release Flow](./docs/release-flow.md)
- [Codex Development And Release Runbook](./docs/codex-dev-release.zh-CN.md)
- [Service Cutover](./docs/service-cutover.md)
- [Docs Index](./docs/README.md)
- [中文文档索引](./docs/README.zh-CN.md)
