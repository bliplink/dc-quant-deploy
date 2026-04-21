# DC Quant Deploy 用户手册

本文面向第一次接触 DC Quant 的用户，目标是在一台 Linux 服务器上通过 Docker Compose 拉起完整系统。

## 1. 系统包含什么

`dc-quant-deploy` 是 DC 量化交易系统的单机部署仓库，默认包含：

- `zookeeper`：服务注册中心。
- `gateway` / `GW`：HTTP、MCP、Web API 入口。
- `MDSvr`：行情与市场数据服务。
- `APSSvr`：应用服务接口。
- `QuantSvr`：实盘/运行时策略服务。
- `INDSvr`：策略生成与候选策略服务。
- `SIMSvr`：回测、优化、发布服务。
- `BatchSvr`：报表与批处理任务服务。
- `web`：前端静态站点。
- `ClickHouse`：唯一数据库，系统不需要 MySQL。

部署方式固定为单机 Docker Compose。正式发布以镜像 tag 为准，不建议生产环境继续用“单独上传 jar”作为标准发布方式。

## 2. 服务器要求

推荐环境：

- Ubuntu 22.04 或兼容 Linux 发行版。
- Docker Engine。
- Docker Compose plugin。
- `git`、`curl`、`bash`。
- 至少 8 GB 内存，生产环境建议更高。
- 服务器开放所需端口。

默认端口：

- `80`：web。
- `2181`：ZooKeeper。
- `3000`、`3001`、`3002`：gateway / GW。
- `30028`：MDSvr。
- `30035`：APSSvr。
- `30042`：QuantSvr。
- `30044`：INDSvr。
- `30045`：SIMSvr。
- `30046`：BatchSvr。
- `8123`：ClickHouse HTTP。
- `9000`：ClickHouse native。

如果端口已被占用，需要先停止冲突进程或修改 `.env.prod` 与相关配置。

## 3. 安装 Docker

如果服务器还没有 Docker，可以按下面方式安装：

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

如果使用普通用户部署，把该用户加入 `docker` 组后需要重新登录：

```bash
usermod -aG docker <your-user>
```

## 4. 下载部署仓库

建议把 Git 仓库放在运行目录之外，例如：

```bash
mkdir -p /opt/source
cd /opt/source
git clone https://github.com/bliplink/dc-quant-deploy.git
cd dc-quant-deploy
```

运行目录由 `.env.prod` 的 `DEPLOY_ROOT` 决定。初始化后，运行目录只需要保留：

- `${DEPLOY_ROOT}/control`
- `${DEPLOY_ROOT}/data`
- `${DEPLOY_ROOT}/log`

## 5. 准备配置文件

复制示例文件：

```bash
cp .env.standalone.example .env.prod
cp -a control.prod.example control.prod
```

编辑 `.env.prod`：

```bash
vi .env.prod
```

关键配置：

```dotenv
COMPOSE_PROJECT_NAME=dc-quant-deploy
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

如果镜像仓库要求登录，先执行：

```bash
docker login ghcr.io
```

并把 `.env.prod` 中的 `REQUIRE_GHCR_LOGIN=true`。

## 6. 配置 control

`control.prod/` 是本机部署实例配置，不要提交到 Git。

至少需要确认：

- `control.prod/ATSConfig.ini`
- `control.prod/DBPoolConfig.ini`
- `control.prod/jaas.ini`
- `control.prod/dc.dat`

说明：

- `dc.dat` 是 license 文件。
- `DBPoolConfig.ini` 只需要 ClickHouse 配置。
- 不需要 MySQL 配置。
- 密码、密钥、生产 IP 不要提交到 Git。

部署时脚本会把 `control.prod/` 同步到 `${DEPLOY_ROOT}/control`。

## 7. ClickHouse 两种模式

### 7.1 没有现成 ClickHouse

使用内置模式：

```dotenv
CLICKHOUSE_MODE=embedded
CLICKHOUSE_HOST=127.0.0.1
CLICKHOUSE_HTTP_PORT=8123
CLICKHOUSE_NATIVE_PORT=9000
```

执行 `deploy.sh` 时会：

- 启动 ClickHouse 容器。
- 自动创建 `dc` 数据库。
- 自动执行 `clickhouse/init/10-schema/`。
- 自动执行 `clickhouse/init/20-view/`。
- 不自动执行 `90-optional-seed/`。

### 7.2 已有 ClickHouse

使用外置模式：

```dotenv
CLICKHOUSE_MODE=external
CLICKHOUSE_HOST=<your-clickhouse-host>
CLICKHOUSE_HTTP_PORT=8123
CLICKHOUSE_USERNAME=default
CLICKHOUSE_PASSWORD=<your-password>
```

外置模式下部署脚本不会启动 ClickHouse，也不会自动改库。用户需要手动初始化：

```bash
./clickhouse/apply-init.sh
```

默认初始化只建库、建表、建视图，不灌样例数据。

## 8. 一键部署

仓库提供两种一键部署入口。

新机器、没有 ClickHouse 时：

```bash
./deploy-standalone.sh
```

已有 ClickHouse 时：

```bash
./deploy-with-external-clickhouse.sh
```

两个入口都会自动完成：

- 校验 Docker、Compose、配置文件。
- 创建 `${DEPLOY_ROOT}/control`、`${DEPLOY_ROOT}/data`、`${DEPLOY_ROOT}/log`。
- 备份旧的 `${DEPLOY_ROOT}/control`。
- 同步 `control.prod/` 到 `${DEPLOY_ROOT}/control`。
- 生成 `compose.override.generated.yaml`。
- 拉取镜像。
- 启动 ZooKeeper。
- 按模式启动或连接 ClickHouse。
- 启动 Java 服务和 web。
- 校验端口与基础运行状态。

底层仍然保留 `deploy.sh`，但普通用户建议优先使用这两个模式明确的一键入口。

## 9. 验证系统

查看容器：

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml ps
```

检查端口：

```bash
curl -I http://127.0.0.1/web/
curl http://127.0.0.1:8123/?query=SELECT%201
printf ruok | nc -w 3 127.0.0.1 2181
```

查看日志：

```bash
docker logs dc-gateway --tail 100
docker logs dc-apssvr --tail 100
tail -n 100 ${DEPLOY_ROOT}/log/APSSvr.log
```

检查 ClickHouse 表：

```bash
curl 'http://127.0.0.1:8123/?query=SHOW%20TABLES%20FROM%20dc'
```

系统启动成功的基本标准：

- `dc-zookeeper` 运行，`ruok` 返回 `imok`。
- `dc-gateway` 运行，`3002` 可访问。
- `dc-web` 运行，`/web/` 可访问。
- Java 服务容器都处于 `Up`。
- ClickHouse 中存在 `dc.signal`、`dc.quant_order`、`dc.strategy_candidate` 等核心表。

## 10. 日常启停

进入部署仓库：

```bash
cd /opt/source/dc-quant-deploy
```

重启单个服务：

```bash
./restart-service.sh apssvr
```

先演练不执行：

```bash
./restart-service.sh apssvr --dry-run
```

停止单个服务：

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml stop apssvr
```

启动单个服务：

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml up -d --no-deps apssvr
```

查看单个服务日志：

```bash
docker logs dc-apssvr --tail 200
```

常用服务名：

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

## 11. 修改日志级别和运行时配置

默认使用镜像内置配置。只有当宿主机存在覆盖文件时，部署脚本才会生成单文件挂载。

覆盖文件目录：

```bash
${DEPLOY_ROOT}/control/overrides
```

支持的覆盖文件：

- `GW/config/mcpTools.tsv`
- `GW/config/apiKeyList.csv`
- `GW/config/spring-gw-client.xml`
- `GW/config/log4j.ini`
- `MDSvr/config/log4j.ini`
- `APSSvr/config/log4j.ini`
- `QuantSvr/config/log4j.ini`
- `INDSvr/config/log4j.ini`
- `SIMSvr/config/log4j.ini`
- `BatchSvr/config/log4j.ini`

修改 `log4j.ini` 通常可以热生效。新增覆盖文件后，需要重新生成 override 并重启对应服务：

```bash
./restart-service.sh apssvr
```

`spring-gw-client.xml` 是启动配置，修改后必须重启 `gateway`。

## 12. 升级镜像

修改 `.env.prod` 中对应 tag：

```dotenv
APSSVR_TAG=v0.0.2
```

只升级一个服务：

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml pull apssvr
./restart-service.sh apssvr
```

升级全量系统：

```bash
./validate.sh
./deploy.sh
```

生产环境建议逐服务升级，先验证一个服务稳定后再继续下一个服务。

## 13. 回滚

全量部署失败时：

```bash
./rollback.sh
```

逐服务切换时可以使用：

```bash
./rollback-service.sh apssvr
```

如果已经完成纯容器化并移除了旧脚本，推荐按镜像 tag 回滚：

```bash
vi .env.prod
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml pull apssvr
./restart-service.sh apssvr
```

注意：回滚不会删除 ClickHouse 数据卷，避免误删业务数据。

## 14. 定时任务

如果某个服务需要定时重启，可以直接使用 `restart-service.sh`。

示例：每天 `00:05` 重启 APSSvr：

```cron
5 0 * * * cd /opt/source/dc-quant-deploy && ./restart-service.sh apssvr >> /opt/dc-runtime/log/cron-apssvr-restart.log 2>&1
```

安装前先备份 crontab：

```bash
crontab -l > ~/crontab.backup.$(date +%Y%m%d%H%M%S).txt
crontab -e
```

## 15. 目录说明

部署仓库目录：

```text
/opt/source/dc-quant-deploy
```

运行目录：

```text
${DEPLOY_ROOT}
├── control
├── data
└── log
```

重要规则：

- `control` 保存当前实例配置。
- `data` 保存持久化数据，包括 ZooKeeper 和可选 ClickHouse 数据。
- `log` 保存服务日志。
- 不要把 `.env.prod`、`control.prod/`、运行目录提交到 Git。

## 16. 常见问题

### 镜像拉取失败

如果镜像是私有的，先登录：

```bash
docker login ghcr.io
```

再设置：

```dotenv
REQUIRE_GHCR_LOGIN=true
```

### `docker compose` 找不到

确认安装的是 Compose plugin：

```bash
docker compose version
```

不是旧命令 `docker-compose`。

### ClickHouse schema 校验失败

如果使用 `embedded`，查看 ClickHouse 容器日志：

```bash
docker logs dc-clickhouse --tail 200
```

如果使用 `external`，先手动执行：

```bash
./clickhouse/apply-init.sh
```

### ZooKeeper 不通

检查：

```bash
docker logs dc-zookeeper --tail 200
printf ruok | nc -w 3 127.0.0.1 2181
```

ZooKeeper 数据默认持久化到：

```text
${DEPLOY_ROOT}/data/zookeeper
```

### Web 能打开但接口不通

优先检查 gateway：

```bash
docker logs dc-gateway --tail 200
curl http://127.0.0.1:3002/
```

再检查 `control/ATSConfig.ini` 中的服务地址与端口。

### 服务日志没有写入

确认运行目录权限：

```bash
ls -la ${DEPLOY_ROOT}
ls -la ${DEPLOY_ROOT}/log
```

并确认 `.env.prod` 中的 `RUNTIME_UID`、`RUNTIME_GID` 与部署用户匹配。

## 17. 最小命令清单

从零部署的最短路径：

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

日常最常用命令：

```bash
./restart-service.sh apssvr
docker logs dc-apssvr --tail 200
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml ps
```
