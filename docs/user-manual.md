# DC Quant Deploy User Manual

This manual explains how to install and operate the DC Quant stack on one Linux host with Docker Compose.

## 1. What Is Included

`dc-quant-deploy` starts the complete runtime skeleton:

- `zookeeper`: service registry.
- `gateway` / `GW`: HTTP, MCP, and Web API entry.
- `MDSvr`: market data service.
- `APSSvr`: application service API.
- `QuantSvr`: runtime trading and strategy service.
- `INDSvr`: strategy generation service.
- `SIMSvr`: backtest, optimization, and publishing service.
- `BatchSvr`: reports and batch jobs.
- `web`: static frontend.
- `ClickHouse`: the only database used by this stack.

The deployment shape is single-host Docker Compose. Production releases should use versioned image tags instead of uploading individual JAR files.

## 2. Requirements

Recommended host:

- Ubuntu 22.04 or compatible Linux.
- Docker Engine.
- Docker Compose plugin.
- `git`, `curl`, and `bash`.
- At least 8 GB memory. Production should use more.

Default ports:

- `80`: web.
- `2181`: ZooKeeper.
- `3000`, `3001`, `3002`: gateway / GW.
- `30028`: MDSvr.
- `30035`: APSSvr.
- `30042`: QuantSvr.
- `30044`: INDSvr.
- `30045`: SIMSvr.
- `30046`: BatchSvr.
- `8123`: ClickHouse HTTP.
- `9000`: ClickHouse native.

## 3. Install Docker

```bash
apt-get update
apt-get install -y ca-certificates curl gnupg git netcat-openbsd
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
docker --version
docker compose version
```

For a non-root deployment user:

```bash
usermod -aG docker <your-user>
```

Start a new SSH session after changing group membership.

## 4. Clone The Repository

Keep the Git checkout outside the runtime root:

```bash
mkdir -p /opt/source
cd /opt/source
git clone https://github.com/bliplink/dc-quant-deploy.git
cd dc-quant-deploy
```

The runtime root is controlled by `DEPLOY_ROOT`. After initialization it should only need:

- `${DEPLOY_ROOT}/control`
- `${DEPLOY_ROOT}/data`
- `${DEPLOY_ROOT}/log`

## 5. Prepare Configuration

```bash
cp .env.standalone.example .env.prod
cp -a control.prod.example control.prod
```

Edit `.env.prod`:

```bash
vi .env.prod
```

Important values:

```dotenv
DEPLOY_ROOT=/opt/dc-runtime
RUNTIME_UID=1000
RUNTIME_GID=1000
SERVICE_HOST=127.0.0.1
REQUIRE_GHCR_LOGIN=false

CLICKHOUSE_MODE=embedded
CLICKHOUSE_IMAGE_TAG=25.9.3.48
CLICKHOUSE_DB_NAME=dc
CLICKHOUSE_HOST=127.0.0.1
CLICKHOUSE_HTTP_PORT=8123
CLICKHOUSE_NATIVE_PORT=9000
CLICKHOUSE_USERNAME=default
CLICKHOUSE_PASSWORD=
```

If GHCR images require authentication:

```bash
docker login ghcr.io
```

Then set:

```dotenv
REQUIRE_GHCR_LOGIN=true
```

## 6. Prepare `control.prod`

`control.prod/` is your local deployment instance. Do not commit it.

Check these files:

- `control.prod/ATSConfig.ini`
- `control.prod/DBPoolConfig.ini`
- `control.prod/jaas.ini`
- `control.prod/dc.dat`

Notes:

- `dc.dat` is the license file.
- `DBPoolConfig.ini` only needs ClickHouse settings.
- MySQL is not required.
- Secrets and production endpoints must stay local.

During deployment, `control.prod/` is copied to `${DEPLOY_ROOT}/control`.

## 7. ClickHouse Modes

### Embedded ClickHouse

Use this when you do not already have ClickHouse:

```dotenv
CLICKHOUSE_MODE=embedded
CLICKHOUSE_HOST=127.0.0.1
CLICKHOUSE_HTTP_PORT=8123
CLICKHOUSE_NATIVE_PORT=9000
```

`deploy.sh` starts ClickHouse and initializes the `dc` database, schema, and views. Optional seed scripts are not executed automatically.

### External ClickHouse

Use this when ClickHouse already exists:

```dotenv
CLICKHOUSE_MODE=external
CLICKHOUSE_HOST=<your-clickhouse-host>
CLICKHOUSE_HTTP_PORT=8123
CLICKHOUSE_USERNAME=default
CLICKHOUSE_PASSWORD=<your-password>
```

The deployment script will not start or mutate ClickHouse. Initialize manually when needed:

```bash
./clickhouse/apply-init.sh
```

## 8. One-Command Deployment

There are two one-command entries.

For a new server without ClickHouse:

```bash
./deploy-standalone.sh
```

For a server that already has ClickHouse:

```bash
./deploy-with-external-clickhouse.sh
```

Both scripts validate inputs, prepare runtime directories, sync `control.prod/`, generate optional override mounts, pull images, start ZooKeeper, handle ClickHouse according to the selected mode, start the services, and validate ports.

The lower-level `deploy.sh` still exists, but normal users should prefer the mode-specific scripts.

## 9. Verify The Stack

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml ps
curl -I http://127.0.0.1/web/
curl 'http://127.0.0.1:8123/?query=SELECT%201'
printf ruok | nc -w 3 127.0.0.1 2181
docker logs dc-gateway --tail 100
```

Minimum healthy state:

- ZooKeeper returns `imok`.
- Gateway is running and port `3002` is reachable.
- Web is reachable at `/web/`.
- Java service containers are `Up`.
- ClickHouse has core tables such as `dc.signal`, `dc.quant_order`, and `dc.strategy_candidate`.

## 10. Operations

Restart one service:

```bash
./restart-service.sh apssvr
```

Dry run:

```bash
./restart-service.sh apssvr --dry-run
```

Stop one service:

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml stop apssvr
```

Start one service without dependencies:

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml up -d --no-deps apssvr
```

View logs:

```bash
docker logs dc-apssvr --tail 200
tail -n 100 ${DEPLOY_ROOT}/log/APSSvr.log
```

## 11. Runtime Overrides

Image-bundled config is the default. Host overrides are mounted only when files exist under:

```bash
${DEPLOY_ROOT}/control/overrides
```

Supported files:

- `GW/config/mcpTools.tsv`
- `GW/config/apiKeyList.csv`
- `GW/config/spring-gw-client.xml`
- `GW/config/log4j.ini`
- `<Service>/config/log4j.ini` for `MDSvr`, `APSSvr`, `QuantSvr`, `INDSvr`, `SIMSvr`, and `BatchSvr`.

After adding a new override file, restart the service once:

```bash
./restart-service.sh apssvr
```

## 12. Upgrade And Rollback

To upgrade one service, change its tag in `.env.prod`:

```dotenv
APSSVR_TAG=v0.0.2
```

Then:

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml pull apssvr
./restart-service.sh apssvr
```

Full deployment rollback:

```bash
./rollback.sh
```

If the stack is fully containerized, rollback by restoring the previous image tag and recreating the service.

## 13. Scheduled Restart

Example: restart APSSvr daily at `00:05`:

```cron
5 0 * * * cd /opt/source/dc-quant-deploy && ./restart-service.sh apssvr >> /opt/dc-runtime/log/cron-apssvr-restart.log 2>&1
```

## 14. Minimal Command List

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
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml ps
```
