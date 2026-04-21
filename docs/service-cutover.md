# Service Cutover

This document describes the production migration pattern for switching one service at a time.

## Current First Target

The first supported targets are `batchsvr` and `simsvr`.

- legacy service: `BatchSvr`
- container: `dc-batchsvr`
- port: `30046`
- image: `ghcr.io/bliplink/batchsvr:${BATCHSVR_TAG}`
- legacy service: `SIMSvr`
- container: `dc-simsvr`
- port: `30045`
- image: `ghcr.io/SKT-Walter/simsvr:${SIMSVR_TAG}`

## Production Defaults

Use `.env.prod.batchsvr.example` as the production template for the first BatchSvr cutover.

Important defaults:

- `DEPLOY_ROOT=/data/strategy`
- `RUNTIME_UID=1000`
- `RUNTIME_GID=1000`
- `SERVICE_HOST=14.0.47.20`
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
./deploy-service.sh simsvr --dry-run
./rollback-service.sh simsvr --dry-run
```

The dry run must show only the `batchsvr` service target. It must not call the full `deploy.sh`.

`SERVICE_HOST` is the host used by the cutover scripts when checking whether the service port is open or closed. Use the production bind address, not always `127.0.0.1`, because existing DC services may bind directly to the server IP.

## Docker Prerequisite

For Ubuntu 22.04 production hosts without Docker, install Docker Engine and the Compose plugin first. This step only prepares Docker; it must not start any DC service container yet.

```bash
apt-get update
apt-get install -y ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
usermod -aG docker dc
docker --version
docker compose version
systemctl is-active docker
```

After adding `dc` to the `docker` group, start a fresh SSH session for the group change to take effect. If the current automation session still cannot access Docker as `dc`, use `newgrp docker` or reconnect before running the cutover script.

## Service Cutover

1. Copy `.env.prod.batchsvr.example` to `.env.prod` and adjust tags if needed.
2. Confirm Docker and Compose are ready.
3. Confirm GHCR login is ready.
4. Run `./deploy-service.sh <service> --dry-run`.
5. Run `./deploy-service.sh <service>`.
6. Verify the target container is running.
7. Verify the target port is reachable.
8. Review `docker logs <container> --tail 200`.
9. Review the target service log under `/data/strategy/log/`.
10. Confirm the other legacy service PIDs did not change.

## Rollback

Rollback only BatchSvr:

```bash
./rollback-service.sh batchsvr
```

Rollback stops only the `batchsvr` container and starts only the legacy `BatchSvr`.

## Per-Service Runtime Mounts

Java services run as `1000:1000` in the container to keep host log/data files compatible with legacy rollback. Current service images may have root-owned application directories, so Compose mounts these paths directly and prevents the entrypoint from creating symlinks inside the image:

- `${DEPLOY_ROOT}/data -> /srv/dc/dc/BatchSvr/data`
- `${DEPLOY_ROOT}/log -> /srv/dc/dc/BatchSvr/log`
- `${DEPLOY_ROOT}/data -> /srv/dc/dc/SIMSvr/data`
- `${DEPLOY_ROOT}/log -> /srv/dc/dc/SIMSvr/log`

When a service declares service-specific mounts, keep the common mounts explicit as well:

- `${DEPLOY_ROOT}/control -> /srv/dc/control:ro`
- `${DEPLOY_ROOT}/data -> /srv/dc/data`
- `${DEPLOY_ROOT}/log -> /srv/dc/log`

Compose does not merge list values from the YAML anchor; a service-level `volumes` list replaces the base list.

## ClickHouse Checks

This first production cutover is external-ClickHouse only. `deploy-service.sh batchsvr` checks:

- `CLICKHOUSE_MODE=external`
- HTTP connectivity to `CLICKHOUSE_HOST:CLICKHOUSE_HTTP_PORT`
- the `dc.signal` table exists
- at least one `dc.strategy_system_daily_report*` table exists

The script does not initialize or mutate production ClickHouse during single-service cutover.

For `simsvr`, `deploy-service.sh simsvr` checks that `strategy_backtest_task` and `backtest_result` exist.

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
