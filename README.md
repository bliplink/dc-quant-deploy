# dc-quant-deploy

`dc-quant-deploy` is the open deployment repository for the DC quantitative trading stack.

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
- real production `dc.dat`
- the ZooKeeper source tree itself

The ZooKeeper source and image pipeline live in the separate repository:

- `https://github.com/bliplink/zookeeper`
- image: `ghcr.io/bliplink/zookeeper`

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
3. Replace placeholders in `control.prod/` and provide the real `dc.dat` content.
4. Run `./validate.sh`.
5. Run `./deploy.sh`.

The deployment script will:

1. validate Docker and config inputs
2. back up the current `control/`
3. sync `control.prod/` into `${DEPLOY_ROOT}/control`
4. stop legacy services if the old `scripts/stop` entry exists
5. pull images
6. start `clickhouse` and `zookeeper`
7. wait for ClickHouse schema readiness
8. start the Java services and `web`

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
