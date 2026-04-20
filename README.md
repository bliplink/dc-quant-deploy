# dc-quant-deploy

`dc-quant-deploy` is the open deployment repository for the DC quantitative trading stack.

Language:

- English: [README.md](./README.md)
- 简体中文: [README.zh-CN.md](./README.zh-CN.md)

It is designed as a single-host Docker Compose delivery that lets external users bring up the full runtime skeleton without touching the original production machine layout:

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

## Scope

- Deployment shape: single-host Docker Compose
- Database boundary: ClickHouse only
- Release model: versioned container images
- `GW = gateway`

This repository does not include:

- real production secrets
- real production `control.prod/`

## Repository Layout

- [compose.yaml](./compose.yaml): main deployment topology
- [.env.example](./.env.example): public deployment variables template
- [deploy.sh](./deploy.sh): one-click deployment entry
- [validate.sh](./validate.sh): preflight validation
- [rollback.sh](./rollback.sh): rollback entry
- [control.template](./control.template): placeholder-based control templates
- [control.prod.example](./control.prod.example): sanitized example control files
- [clickhouse](./clickhouse): ClickHouse bootstrap SQL and helper scripts
- [zookeeper.example](./zookeeper.example): sanitized ZooKeeper runtime config example
- [docs/architecture.md](./docs/architecture.md): service and image map
- [docs/database.md](./docs/database.md): ClickHouse initialization contract
- [docs/release-flow.md](./docs/release-flow.md): image-based release flow

## Quick Start

1. Copy `.env.example` to `.env.prod`.
2. Copy `control.prod.example/` to `control.prod/`.
3. Replace placeholders in `control.prod/`.
4. Run `./validate.sh`.
5. Run `./deploy.sh`.

## ClickHouse Modes

The repository supports two ClickHouse deployment modes.

1. `embedded`
   The user does not already have ClickHouse. `deploy.sh` starts the ClickHouse container from `compose.yaml` and runs the initialization scripts automatically.
2. `external`
   The user already has ClickHouse. The user handles database initialization manually. `deploy.sh` does not start a ClickHouse container and does not modify the existing database.

Set these values in `.env.prod`:

- `CLICKHOUSE_MODE=embedded` or `CLICKHOUSE_MODE=external`
- `CLICKHOUSE_HOST`
- `CLICKHOUSE_HTTP_PORT`
- `CLICKHOUSE_USERNAME`
- `CLICKHOUSE_PASSWORD`

The deployment script will:

1. validate Docker and config inputs
2. back up the current `control/`
3. sync `control.prod/` into `${DEPLOY_ROOT}/control`
4. stop legacy services if the old `scripts/stop` entry exists
5. start `zookeeper`
6. start `clickhouse` only when `CLICKHOUSE_MODE=embedded`
7. run the ClickHouse initialization scripts only when `CLICKHOUSE_MODE=embedded`
8. wait for ClickHouse schema readiness
9. start the Java services and `web`

If `CLICKHOUSE_MODE=external`, initialize the database yourself before deployment. The provided helper is:

- `./clickhouse/apply-init.sh`

## ClickHouse Contract

ClickHouse is the only database in this public deployment package.

Default behavior:

- creates database `dc` if needed
- initializes core schema from `clickhouse/init/10-schema/`
- initializes view objects from `clickhouse/init/20-view/`
- does not auto-run `90-optional-seed/`

Optional migration, cleanup, and verification SQL is intentionally kept out of the default bootstrap path.

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

## Secrets And Local Overrides

Do not commit these back into Git:

- `.env.prod`
- `control.prod/`
- `${DEPLOY_ROOT}/control`
- `${DEPLOY_ROOT}/clickhouse/data`
- `${DEPLOY_ROOT}/clickhouse/log`

## More Docs

- [Architecture](./docs/architecture.md)
- [Database](./docs/database.md)
- [Release Flow](./docs/release-flow.md)
- [Docs Index](./docs/README.md)
- [文档索引](./docs/README.zh-CN.md)
