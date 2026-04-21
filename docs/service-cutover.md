# Service Cutover

This document describes the production migration pattern for switching one service at a time.

## Current First Target

The first supported target is `batchsvr`.

- legacy service: `BatchSvr`
- container: `dc-batchsvr`
- port: `30046`
- image: `ghcr.io/bliplink/batchsvr:${BATCHSVR_TAG}`

## Production Defaults

Use `.env.prod.batchsvr.example` as the production template for the first BatchSvr cutover.

Important defaults:

- `DEPLOY_ROOT=/data/strategy`
- `RUNTIME_UID=1000`
- `RUNTIME_GID=1000`
- `CLICKHOUSE_MODE=external`
- `CLICKHOUSE_HOST=14.0.47.20`
- `CLICKHOUSE_USERNAME=default`
- `CLICKHOUSE_PASSWORD=change-me-in-local-env-prod`

Keep the real production password only in `.env.prod` on the production host. Do not commit it.

## Dry Run

Run a dry run before touching the service:

```bash
./deploy-service.sh batchsvr --dry-run
./rollback-service.sh batchsvr --dry-run
```

The dry run must show only the `batchsvr` service target. It must not call the full `deploy.sh`.

## BatchSvr Cutover

1. Copy `.env.prod.batchsvr.example` to `.env.prod` and adjust tags if needed.
2. Confirm Docker and Compose are ready.
3. Confirm GHCR login is ready.
4. Run `./deploy-service.sh batchsvr --dry-run`.
5. Run `./deploy-service.sh batchsvr`.
6. Verify `dc-batchsvr` is running.
7. Verify port `30046` is reachable.
8. Review `docker logs dc-batchsvr --tail 200`.
9. Review `/data/strategy/log/BatchSvr.log`.
10. Confirm the other legacy service PIDs did not change.

## Rollback

Rollback only BatchSvr:

```bash
./rollback-service.sh batchsvr
```

Rollback stops only the `batchsvr` container and starts only the legacy `BatchSvr`.

## ClickHouse Checks

This first production cutover is external-ClickHouse only. `deploy-service.sh batchsvr` checks:

- `CLICKHOUSE_MODE=external`
- HTTP connectivity to `CLICKHOUSE_HOST:CLICKHOUSE_HTTP_PORT`
- the `dc.signal` table exists
- at least one `dc.strategy_system_daily_report*` table exists

The script does not initialize or mutate production ClickHouse during single-service cutover.

## Later Order

Recommended order after BatchSvr is stable:

1. `simsvr`
2. `indsvr`
3. `apssvr`
4. `mdsvr`
5. `quantsvr`
6. `gateway`
7. `web`
8. `zookeeper`

Do not switch `zookeeper` early. It is the registry backbone and should be moved after application services are proven stable.
