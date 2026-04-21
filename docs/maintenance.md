# Maintenance Guide

This guide describes common maintenance tasks after deployment.

## 1. Check Status

```bash
cd /opt/source/dc-quant-deploy
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml ps
```

For embedded ClickHouse:

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml --profile embedded-clickhouse ps
```

## 2. Start And Stop Services

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

Service names:

- `zookeeper`
- `gateway`
- `mdsvr`
- `apssvr`
- `quantsvr`
- `indsvr`
- `simsvr`
- `batchsvr`
- `web`
- `clickhouse`

## 3. Logs

Container logs:

```bash
docker logs dc-apssvr --tail 200
docker logs dc-gateway --tail 200
```

Host logs:

```bash
tail -n 100 ${DEPLOY_ROOT}/log/APSSvr.log
tail -n 100 ${DEPLOY_ROOT}/log/QuantSvr.log
```

Recent error scan:

```bash
for c in dc-gateway dc-mdsvr dc-apssvr dc-quantsvr dc-indsvr dc-simsvr dc-batchsvr dc-web dc-zookeeper; do
  echo "===== $c ====="
  docker logs "$c" --since 5m 2>&1 | grep -Ei 'ERROR|Exception|timeout|permission denied|address already in use' || true
done
```

## 4. Health Checks

Web:

```bash
curl -I http://127.0.0.1/web/
```

ZooKeeper:

```bash
printf ruok | nc -w 3 127.0.0.1 2181
```

ClickHouse:

```bash
curl 'http://127.0.0.1:8123/?query=SELECT%201'
```

Ports:

```bash
ss -lntp | grep -E '(:80|:2181|:3000|:3001|:3002|:30028|:30035|:30042|:30044|:30045|:30046|:8123|:9000)\b'
```

## 5. Log Level Changes

Image-bundled config is the default. Put overrides under:

```text
${DEPLOY_ROOT}/control/overrides/<Service>/config/log4j.ini
```

Example:

```text
${DEPLOY_ROOT}/control/overrides/APSSvr/config/log4j.ini
```

After adding a new override file, restart the service once:

```bash
./restart-service.sh apssvr
```

An already-mounted `log4j.ini` is usually hot-reloaded.

## 6. Upgrade Images

Change the service tag in `.env.prod`:

```dotenv
APSSVR_TAG=v0.0.2
```

Pull and restart:

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml pull apssvr
./restart-service.sh apssvr
```

Verify after upgrade:

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml ps
docker logs dc-apssvr --tail 200
```

## 7. Backup

Back up at least:

- `.env.prod`
- `control.prod/`
- `${DEPLOY_ROOT}/control`
- `${DEPLOY_ROOT}/data`
- `${DEPLOY_ROOT}/log`

Example:

```bash
TS=$(date +%Y%m%d-%H%M%S)
BACKUP=/opt/dc-backup/$TS
mkdir -p "$BACKUP"
cp -a .env.prod "$BACKUP/env.prod"
cp -a control.prod "$BACKUP/control.prod"
cp -a ${DEPLOY_ROOT}/control "$BACKUP/control"
cp -a ${DEPLOY_ROOT}/data "$BACKUP/data"
cp -a ${DEPLOY_ROOT}/log "$BACKUP/log"
```

For external ClickHouse, follow your existing ClickHouse backup policy.

## 8. Rollback

Recommended rollback is image-tag based:

```bash
vi .env.prod
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml pull apssvr
./restart-service.sh apssvr
```

For a failed full deployment:

```bash
./rollback.sh
```

Rollback does not delete ClickHouse data.

## 9. Scheduled Restart

If a service needs scheduled restart:

```cron
5 0 * * * cd /opt/source/dc-quant-deploy && ./restart-service.sh apssvr >> /opt/dc-runtime/log/cron-apssvr-restart.log 2>&1
```

Back up crontab first:

```bash
crontab -l > ~/crontab.backup.$(date +%Y%m%d%H%M%S).txt
crontab -e
```
