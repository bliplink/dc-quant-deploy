# DC Quant Deploy 用户手册

## 1. 安装依赖

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

## 2. 下载仓库

```bash
mkdir -p /opt/source
cd /opt/source
git clone https://github.com/bliplink/dc-quant-deploy.git
cd dc-quant-deploy
```

## 3. 方式一：从无到有部署

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

## 4. 方式二：已有 ClickHouse 后部署

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

## 5. 验证

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml ps
curl -I http://127.0.0.1/web/
printf ruok | nc -w 3 127.0.0.1 2181
curl 'http://127.0.0.1:8123/?query=SELECT%201'
```

## 6. 维护

```bash
./restart-service.sh apssvr
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml stop apssvr
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml up -d --no-deps apssvr
docker logs dc-apssvr --tail 200
tail -n 100 ${DEPLOY_ROOT}/log/APSSvr.log
```

## 7. 升级

```bash
vi .env.prod
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml pull apssvr
./restart-service.sh apssvr
```

## 8. 回滚

```bash
vi .env.prod
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml pull apssvr
./restart-service.sh apssvr
```
