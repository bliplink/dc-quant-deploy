# Deployment Modes

`dc-quant-deploy` provides two user-facing one-command deployment entries.

## 1. Standalone Deployment

Use this when the server does not already have ClickHouse.

```bash
./deploy-standalone.sh
```

Recommended setup:

```bash
cp .env.standalone.example .env.prod
cp -a control.prod.example control.prod
vi .env.prod
vi control.prod/ATSConfig.ini
vi control.prod/DBPoolConfig.ini
vi control.prod/jaas.ini
cp /path/to/dc.dat control.prod/dc.dat
./deploy-standalone.sh
```

This entry:

- backs up `.env.prod`
- sets `CLICKHOUSE_MODE=embedded`
- sets `CLICKHOUSE_HOST=127.0.0.1`
- starts the `dc-clickhouse` container
- initializes the container user from `CLICKHOUSE_USERNAME` / `CLICKHOUSE_PASSWORD`
- runs ClickHouse initialization scripts through the native `CLICKHOUSE_NATIVE_PORT`
- starts ZooKeeper, Java services, and web

Safety guard:

- If local ports `8123` or `9000` are already used by another process, the script fails before deployment.
- Do not use this entry on a production host that already has ClickHouse.

## 2. Deployment With Existing ClickHouse

Use this when ClickHouse already exists.

```bash
./deploy-with-external-clickhouse.sh
```

Recommended setup:

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

Set the real ClickHouse values in `.env.prod`:

```dotenv
CLICKHOUSE_MODE=external
CLICKHOUSE_HOST=<your-clickhouse-host>
CLICKHOUSE_HTTP_PORT=8123
CLICKHOUSE_NATIVE_PORT=9000
CLICKHOUSE_DB_NAME=dc
CLICKHOUSE_USERNAME=default
CLICKHOUSE_PASSWORD=<your-password>
```

This entry:

- backs up `.env.prod`
- sets `CLICKHOUSE_MODE=external`
- keeps the existing ClickHouse host, ports, username, and password
- does not start `dc-clickhouse`
- does not mutate an existing ClickHouse instance
- validates connectivity and core schema
- starts ZooKeeper, Java services, and web

If the external database has not been initialized, run:

```bash
./clickhouse/apply-init.sh
```

Default initialization creates the database, tables, and views only. It does not import sample data.

## 3. Choosing A Mode

| Scenario | Entry | ClickHouse behavior |
| --- | --- | --- |
| New server, no database | `./deploy-standalone.sh` | Starts and initializes ClickHouse container |
| Production already has database | `./deploy-with-external-clickhouse.sh` | Uses existing ClickHouse |
| Rehearse app deployment without data migration | `./deploy-with-external-clickhouse.sh` | Keeps existing ClickHouse |
| Verify open-source install from scratch | `./deploy-standalone.sh` | Uses embedded ClickHouse |

## 4. Relationship To `deploy.sh`

`deploy.sh` is the shared lower-level deployment entry. Its behavior is controlled by `CLICKHOUSE_MODE`.

The two mode-specific entries are safety wrappers:

- `deploy-standalone.sh`: sets embedded mode, then calls `deploy.sh`
- `deploy-with-external-clickhouse.sh`: sets external mode, then calls `deploy.sh`

Users should prefer these two entries instead of manually switching `CLICKHOUSE_MODE`.
