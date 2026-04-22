# DC Quant Deploy User Manual

This manual explains how to install, verify, and maintain the DC Quant single-host Docker Compose stack.

## 1. Prepare The Server

Recommended server:

- Ubuntu 22.04 or compatible Linux.
- Docker Engine.
- Docker Compose plugin.
- `git`, `curl`, and `netcat-openbsd`.
- At least 8 GB memory.

Install Docker:

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

Start a new login session before continuing.

## 2. Clone The Repository

Keep the Git checkout outside the runtime root:

```bash
mkdir -p /opt/source
cd /opt/source
git clone https://github.com/bliplink/dc-quant-deploy.git
cd dc-quant-deploy
```

The runtime root is controlled by `DEPLOY_ROOT`. After deployment it only needs:

```text
${DEPLOY_ROOT}/control
${DEPLOY_ROOT}/data
${DEPLOY_ROOT}/log
```

## 3. Choose A Deployment Mode

### Standalone Deployment

Use this when ClickHouse does not already exist.

```bash
cp .env.standalone.example .env.prod
mkdir -p control.prod
cp control.prod.example/ATSConfig.ini control.prod/
cp control.prod.example/DBPoolConfig.ini control.prod/
cp control.prod.example/jaas.ini control.prod/
cp -a control.prod.example/overrides control.prod/
vi .env.prod
vi control.prod/ATSConfig.ini
vi control.prod/DBPoolConfig.ini
vi control.prod/jaas.ini
./deploy-standalone.sh
```

This starts:

- DC application services.
- ZooKeeper.
- The `dc-clickhouse` container.

It also initializes the ClickHouse `dc` database, tables, and views.

### Existing ClickHouse Deployment

Use this when ClickHouse already exists.

```bash
cp .env.external-clickhouse.example .env.prod
mkdir -p control.prod
cp control.prod.example/ATSConfig.ini control.prod/
cp control.prod.example/DBPoolConfig.ini control.prod/
cp control.prod.example/jaas.ini control.prod/
cp -a control.prod.example/overrides control.prod/
vi .env.prod
vi control.prod/ATSConfig.ini
vi control.prod/DBPoolConfig.ini
vi control.prod/jaas.ini
./deploy-with-external-clickhouse.sh
```

This deploys the DC application services and ZooKeeper. It does not start `dc-clickhouse` and does not mutate the existing ClickHouse instance.

If the existing ClickHouse is not initialized yet:

```bash
./clickhouse/apply-init.sh
```

Default initialization creates database, tables, and views only. It does not import sample data.

## 4. Key Configuration

`.env.prod` contains local deployment variables. Do not commit it.

Common fields:

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

`control.prod/` contains local control files copied from `control.prod.example/`.

Required files:

- `ATSConfig.ini`
- `DBPoolConfig.ini`
- `jaas.ini`
- `dc.dat`


## 5. Verify Deployment

Check containers:

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml ps
```

Verify web:

```bash
curl -I http://127.0.0.1/web/
```

Verify ZooKeeper:

```bash
printf ruok | nc -w 3 127.0.0.1 2181
```

`imok` means ZooKeeper is healthy.

Verify ClickHouse:

```bash
curl 'http://127.0.0.1:8123/?query=SELECT%201'
curl 'http://127.0.0.1:8123/?query=SHOW%20TABLES%20FROM%20dc'
```

For existing ClickHouse, use the host, username, and password from `.env.prod`.

View logs:

```bash
docker logs dc-gateway --tail 100
docker logs dc-apssvr --tail 100
tail -n 100 ${DEPLOY_ROOT}/log/APSSvr.log
```

## 6. Maintenance

Enter the deployment repository:

```bash
cd /opt/source/dc-quant-deploy
```

Check status:

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml ps
```

Restart a service:

```bash
./restart-service.sh apssvr
```

Stop a service:

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml stop apssvr
```

Start a service:

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml up -d --no-deps apssvr
```

View logs:

```bash
docker logs dc-apssvr --tail 200
tail -n 100 ${DEPLOY_ROOT}/log/APSSvr.log
```

See [Maintenance Guide](./maintenance.md) for more details.

## 7. Upgrade

Change the corresponding image tag in `.env.prod`:

```dotenv
APSSVR_TAG=v0.0.2
```

Pull and restart the service:

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml pull apssvr
./restart-service.sh apssvr
```

Verify again after upgrade.

## 8. Backup

Back up regularly:

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
```

If using external ClickHouse, back it up according to your own ClickHouse operations policy.

## 9. Rollback

The recommended rollback is image-tag based:

1. Change the service tag in `.env.prod` back to the previous version.
2. Pull the previous image.
3. Restart the service.

Example:

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml pull apssvr
./restart-service.sh apssvr
```

For a failed full deployment:

```bash
./rollback.sh
```

Rollback does not delete ClickHouse data.

## 10. Troubleshooting

### Image Pull Fails

If images require authentication:

```bash
docker login ghcr.io
```

Then set:

```dotenv
REQUIRE_GHCR_LOGIN=true
```

### ClickHouse Port Conflict

Standalone deployment uses `8123` and `9000`. If ClickHouse already exists on the server, use:

```bash
./deploy-with-external-clickhouse.sh
```

### ZooKeeper Is Not Reachable

```bash
docker logs dc-zookeeper --tail 200
printf ruok | nc -w 3 127.0.0.1 2181
```

### Web Loads But API Fails

Check GW first:

```bash
docker logs dc-gateway --tail 200
curl http://127.0.0.1:3002/
```

Then check service addresses and ports in `control/ATSConfig.ini`.
