# dc-quant-deploy

`dc-quant-deploy` is the single-host Docker Compose deployment repository for the DC quantitative trading stack.

Language:

- English: [README.md](./README.md)
- Simplified Chinese: [README.zh-CN.md](./README.zh-CN.md)

## What This Repository Provides

It provides two clear one-command deployment modes:

- Standalone deployment: deploy the DC application stack and an embedded ClickHouse container.
- Existing ClickHouse deployment: keep using your existing ClickHouse and deploy only the DC application stack.

Included services:

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

Core contracts:

- Single-host Docker Compose only.
- ClickHouse is the only database. MySQL is not required.
- The runtime root only needs `control/`, `data/`, and `log/`.
- `.env.prod` and runtime data must not be committed.
- `control.prod/dc.dat` is the license file tracked by this repository. Replace it only when you intentionally want to change the default license file.

## Option 1: Standalone Deployment

Use this on a new server or when ClickHouse does not already exist.

```bash
git clone https://github.com/bliplink/dc-quant-deploy.git
cd dc-quant-deploy
cp .env.standalone.example .env.prod
mkdir -p control.prod
cp control.prod.example/ATSConfig.ini control.prod/
cp control.prod.example/DBPoolConfig.ini control.prod/
cp control.prod.example/jaas.ini control.prod/
cp -a control.prod.example/overrides control.prod/
# Review and adjust local deployment values when needed.
vi .env.prod
vi control.prod/ATSConfig.ini
vi control.prod/DBPoolConfig.ini
vi control.prod/jaas.ini
./deploy-standalone.sh
```

The `vi control.prod/*.ini` steps mean: confirm the service addresses, ports, ClickHouse connection, and ZooKeeper authentication values for your environment. If the defaults already match your environment, you can leave them unchanged. `control.prod/dc.dat` is already provided by the repository.

This starts the `dc-clickhouse` container and initializes the `dc` database, tables, and views.

## Option 2: Existing ClickHouse Deployment

Use this when ClickHouse already exists.

```bash
git clone https://github.com/bliplink/dc-quant-deploy.git
cd dc-quant-deploy
cp .env.external-clickhouse.example .env.prod
mkdir -p control.prod
cp control.prod.example/ATSConfig.ini control.prod/
cp control.prod.example/DBPoolConfig.ini control.prod/
cp control.prod.example/jaas.ini control.prod/
cp -a control.prod.example/overrides control.prod/
# Review and adjust local deployment values when needed.
vi .env.prod
vi control.prod/ATSConfig.ini
vi control.prod/DBPoolConfig.ini
vi control.prod/jaas.ini
./deploy-with-external-clickhouse.sh
```

The `vi control.prod/*.ini` steps mean: confirm the service addresses, ports, ClickHouse connection, and ZooKeeper authentication values for your environment. If the defaults already match your environment, you can leave them unchanged. `control.prod/dc.dat` is already provided by the repository.

This does not start `dc-clickhouse` and does not mutate an existing ClickHouse instance.

## Verify

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml ps
curl -I http://127.0.0.1/web/
printf ruok | nc -w 3 127.0.0.1 2181
```

For embedded ClickHouse:

```bash
curl 'http://127.0.0.1:8123/?query=SELECT%201'
```

For existing ClickHouse, verify with the host, username, and password from `.env.prod`.

## Maintenance

Check status:

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml ps
```

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

## Important Files

- `.env.prod`: local deployment variables. Do not commit.
- `control.prod/`: local control files copied from `control.prod.example/`.
- `control.prod/dc.dat`: license file tracked by this repository.
- `${DEPLOY_ROOT}/control`: runtime control files.
- `${DEPLOY_ROOT}/data`: runtime data.
- `${DEPLOY_ROOT}/log`: runtime logs.

## Documentation

- [User Manual](./docs/user-manual.md)
- [Deployment Modes](./docs/deployment-modes.md)
- [Maintenance Guide](./docs/maintenance.md)
- [Architecture](./docs/architecture.md)
- [Database](./docs/database.md)
- [Runtime Overrides](./docs/runtime-overrides.md)
- [Release Flow](./docs/release-flow.md)
- [Docs Index](./docs/README.md)
- [中文文档索引](./docs/README.zh-CN.md)
