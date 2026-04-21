# DC Quant Deploy 用户手册

本文说明如何安装、验证和维护 DC Quant 单机 Docker Compose 系统。

## 1. 部署前准备

服务器建议：

- Ubuntu 22.04 或兼容 Linux。
- Docker Engine。
- Docker Compose plugin。
- `git`、`curl`、`netcat-openbsd`。
- 至少 8 GB 内存。

安装 Docker：

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

如果使用普通用户部署：

```bash
usermod -aG docker <your-user>
```

重新登录后再继续。

## 2. 下载仓库

建议把部署仓库放在运行目录之外：

```bash
mkdir -p /opt/source
cd /opt/source
git clone https://github.com/bliplink/dc-quant-deploy.git
cd dc-quant-deploy
```

运行目录由 `.env.prod` 的 `DEPLOY_ROOT` 决定。部署完成后，运行目录只需要：

```text
${DEPLOY_ROOT}/control
${DEPLOY_ROOT}/data
${DEPLOY_ROOT}/log
```

## 3. 选择部署方式

### 方式一：从无到有部署

适合没有 ClickHouse 的新环境。

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

这个方式会启动：

- DC 应用服务。
- ZooKeeper。
- `dc-clickhouse` 容器。

并自动初始化 ClickHouse 的 `dc` 数据库、表和视图。

### 方式二：已有 ClickHouse 后部署

适合已有 ClickHouse 的环境。

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

这个方式只部署 DC 应用服务和 ZooKeeper，不启动 `dc-clickhouse`，也不会自动修改已有 ClickHouse。

如果已有 ClickHouse 还没有初始化，可以手动执行：

```bash
./clickhouse/apply-init.sh
```

默认初始化只建库、建表、建视图，不导入样例数据。

## 4. 关键配置

`.env.prod` 是本机部署变量，不提交 Git。

常见字段：

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

`control.prod/` 是本机控制文件目录，不提交 Git。

至少需要：

- `ATSConfig.ini`
- `DBPoolConfig.ini`
- `jaas.ini`
- `dc.dat`

说明：

- `dc.dat` 是 license 文件。
- 系统只需要 ClickHouse，不需要 MySQL。
- 密码、密钥、生产地址只保存在本机。

## 5. 验证部署

查看容器：

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml ps
```

验证 Web：

```bash
curl -I http://127.0.0.1/web/
```

验证 ZooKeeper：

```bash
printf ruok | nc -w 3 127.0.0.1 2181
```

返回 `imok` 表示 ZooKeeper 正常。

验证 ClickHouse：

```bash
curl 'http://127.0.0.1:8123/?query=SELECT%201'
curl 'http://127.0.0.1:8123/?query=SHOW%20TABLES%20FROM%20dc'
```

如果使用外置 ClickHouse，请使用 `.env.prod` 中的地址、用户名和密码。

查看服务日志：

```bash
docker logs dc-gateway --tail 100
docker logs dc-apssvr --tail 100
tail -n 100 ${DEPLOY_ROOT}/log/APSSvr.log
```

## 6. 日常维护

进入部署仓库：

```bash
cd /opt/source/dc-quant-deploy
```

查看状态：

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml ps
```

重启服务：

```bash
./restart-service.sh apssvr
```

停止服务：

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml stop apssvr
```

启动服务：

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml up -d --no-deps apssvr
```

查看日志：

```bash
docker logs dc-apssvr --tail 200
tail -n 100 ${DEPLOY_ROOT}/log/APSSvr.log
```

更多维护说明见：[系统维护手册](./maintenance.zh-CN.md)。

## 7. 升级

修改 `.env.prod` 中对应镜像 tag：

```dotenv
APSSVR_TAG=v0.0.2
```

拉取并重启对应服务：

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml pull apssvr
./restart-service.sh apssvr
```

升级后按第 5 节重新验证。

## 8. 备份

建议定期备份：

- `.env.prod`
- `control.prod/`
- `${DEPLOY_ROOT}/control`
- `${DEPLOY_ROOT}/data`
- `${DEPLOY_ROOT}/log`

示例：

```bash
TS=$(date +%Y%m%d-%H%M%S)
BACKUP=/opt/dc-backup/$TS
mkdir -p "$BACKUP"
cp -a .env.prod "$BACKUP/env.prod"
cp -a control.prod "$BACKUP/control.prod"
cp -a ${DEPLOY_ROOT}/control "$BACKUP/control"
cp -a ${DEPLOY_ROOT}/data "$BACKUP/data"
```

如果使用外置 ClickHouse，请按你的 ClickHouse 运维规范单独备份数据库。

## 9. 回滚

推荐按镜像 tag 回滚：

1. 把 `.env.prod` 中的服务 tag 改回旧版本。
2. 拉取旧镜像。
3. 重启对应服务。

示例：

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml pull apssvr
./restart-service.sh apssvr
```

如果是全量部署失败，可以执行：

```bash
./rollback.sh
```

回滚不会删除 ClickHouse 数据。

## 10. 常见问题

### 镜像拉取失败

如果镜像需要认证：

```bash
docker login ghcr.io
```

并设置：

```dotenv
REQUIRE_GHCR_LOGIN=true
```

### ClickHouse 端口冲突

从无到有部署会使用 `8123` 和 `9000`。如果机器上已有 ClickHouse，请使用：

```bash
./deploy-with-external-clickhouse.sh
```

### ZooKeeper 不通

```bash
docker logs dc-zookeeper --tail 200
printf ruok | nc -w 3 127.0.0.1 2181
```

### Web 能打开但接口不通

优先检查 gateway：

```bash
docker logs dc-gateway --tail 200
curl http://127.0.0.1:3002/
```

再检查 `control/ATSConfig.ini` 中的地址和端口。
