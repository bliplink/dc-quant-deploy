# dc-quant-deploy

DC Quant single-node Docker Compose deployment repository.

中文文档: [README.md](README.md)

## Services

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

## Requirements

Default checks:

- CPU >= 2 cores
- Memory >= 8192 MB
- Free disk under `${DEPLOY_ROOT}` >= 20 GB

You can adjust the thresholds in `.env.prod`:

```dotenv
MIN_CPU_CORES=2
MIN_MEMORY_MB=8192
MIN_DISK_GB=20
```

The deployment script stops with a clear message if the machine does not meet the requirements.

## Install From Scratch

Use this mode for a new server, or for an environment without an existing ClickHouse.

```bash
git clone https://github.com/bliplink/dc-quant-deploy.git
cd dc-quant-deploy
./deploy-standalone.sh
```

`deploy-standalone.sh` automatically creates missing runtime files from the repository defaults:

- `.env.prod`
- `control.prod/ATSConfig.ini`
- `control.prod/DBPoolConfig.ini`
- `control.prod/jaas.ini`
- `control.prod/dc.dat`
- `control.prod/overrides/`

This mode starts ClickHouse and runs the default initialization SQL automatically.

## Install With Existing ClickHouse

Use this mode when ClickHouse already exists. The script only checks connectivity and schema; it does not migrate data.

```bash
git clone https://github.com/bliplink/dc-quant-deploy.git
cd dc-quant-deploy
cp .env.external-clickhouse.example .env.prod
vi .env.prod
./deploy-with-external-clickhouse.sh
```

If you need to initialize an existing ClickHouse manually:

```bash
./clickhouse/apply-init.sh
```

## Verify

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml ps
curl -I http://127.0.0.1/web/
printf ruok | nc -w 3 127.0.0.1 2181
curl 'http://127.0.0.1:8123/?query=SELECT%201'
```

## Maintain

Restart one service:

```bash
./restart-service.sh quantsvr
```

Stop one service:

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml stop quantsvr
```

Start one service:

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml up -d --no-deps quantsvr
```

View logs:

```bash
docker logs dc-quantsvr --tail 200
tail -n 100 ${DEPLOY_ROOT}/log/QuantSvr.log
```

Upgrade one service image:

```bash
vi .env.prod
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml pull quantsvr
./restart-service.sh quantsvr
```

Rollback after a failed full deployment:

```bash
./rollback.sh
```

## Runtime Directories

After deployment, the server runtime root only needs:

```text
${DEPLOY_ROOT}/control
${DEPLOY_ROOT}/data
${DEPLOY_ROOT}/log
```

## Optional Overrides

Services use image-bundled defaults unless override files exist under `${DEPLOY_ROOT}/control/overrides`.

Supported override files:

```text
${DEPLOY_ROOT}/control/overrides/GW/config/mcpTools.tsv
${DEPLOY_ROOT}/control/overrides/GW/config/apiKeyList.csv
${DEPLOY_ROOT}/control/overrides/GW/config/spring-gw-client.xml
${DEPLOY_ROOT}/control/overrides/GW/config/log4j.ini
${DEPLOY_ROOT}/control/overrides/<Service>/config/log4j.ini
```

After adding a new override file:

```bash
bash generate-compose-overrides.sh .env.prod compose.override.generated.yaml
./restart-service.sh <service>
```

## Repository Files

This repository keeps only the files needed for deployment and maintenance:

```text
compose.yaml
.env.standalone.example
.env.external-clickhouse.example
deploy.sh
deploy-standalone.sh
deploy-with-external-clickhouse.sh
rollback.sh
restart-service.sh
validate.sh
generate-compose-overrides.sh
control.prod/
control.prod.example/
clickhouse/
README.md
README.en.md
```
