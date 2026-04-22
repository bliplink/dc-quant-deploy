# dc-quant-deploy

DC Quant single-node Docker Compose deployment repository.

DC Quant 单机 Docker Compose 一键部署仓库。

## Services / 服务

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

## Requirements / 机器要求

Default checks:

默认检查：

- CPU >= 2 cores / 2 核
- Memory >= 8192 MB / 内存 8192 MB
- Free disk under `${DEPLOY_ROOT}` >= 20 GB / `${DEPLOY_ROOT}` 可用磁盘 20 GB

You can adjust the thresholds in `.env.prod`:

可在 `.env.prod` 中调整阈值：

```dotenv
MIN_CPU_CORES=2
MIN_MEMORY_MB=8192
MIN_DISK_GB=20
```

The deployment script stops with a clear message if the machine does not meet the requirements.

如果机器不满足要求，部署脚本会提示原因并退出。

## Install From Scratch / 从无到有部署

Use this mode for a new server, or for an environment without an existing ClickHouse.

适合新服务器，或没有现成 ClickHouse 的环境。

```bash
git clone https://github.com/bliplink/dc-quant-deploy.git
cd dc-quant-deploy
./deploy-standalone.sh
```

`deploy-standalone.sh` automatically creates missing runtime files from the repository defaults:

`deploy-standalone.sh` 会自动从仓库默认文件生成缺失的运行配置：

- `.env.prod`
- `control.prod/ATSConfig.ini`
- `control.prod/DBPoolConfig.ini`
- `control.prod/jaas.ini`
- `control.prod/dc.dat`
- `control.prod/overrides/`

This mode starts ClickHouse and runs the default initialization SQL automatically.

该方式会自动启动 ClickHouse，并执行默认初始化 SQL。

## Install With Existing ClickHouse / 使用已有 ClickHouse 部署

Use this mode when ClickHouse already exists. The script only checks connectivity and schema; it does not migrate data.

适合已有 ClickHouse 的环境。脚本只做连通性和 schema 检查，不做数据迁移。

```bash
git clone https://github.com/bliplink/dc-quant-deploy.git
cd dc-quant-deploy
cp .env.external-clickhouse.example .env.prod
vi .env.prod
./deploy-with-external-clickhouse.sh
```

If you need to initialize an existing ClickHouse manually:

如需手动初始化已有 ClickHouse：

```bash
./clickhouse/apply-init.sh
```

## Verify / 验证

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml ps
curl -I http://127.0.0.1/web/
printf ruok | nc -w 3 127.0.0.1 2181
curl 'http://127.0.0.1:8123/?query=SELECT%201'
```

## Maintain / 维护

Restart one service:

重启单个服务：

```bash
./restart-service.sh quantsvr
```

Stop one service:

停止单个服务：

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml stop quantsvr
```

Start one service:

启动单个服务：

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml up -d --no-deps quantsvr
```

View logs:

查看日志：

```bash
docker logs dc-quantsvr --tail 200
tail -n 100 ${DEPLOY_ROOT}/log/QuantSvr.log
```

Upgrade one service image:

升级单个服务镜像：

```bash
vi .env.prod
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml pull quantsvr
./restart-service.sh quantsvr
```

Rollback after a failed full deployment:

全量部署失败后回滚：

```bash
./rollback.sh
```

## Runtime Directories / 运行目录

After deployment, the server runtime root only needs:

部署完成后，服务器运行根目录只需要：

```text
${DEPLOY_ROOT}/control
${DEPLOY_ROOT}/data
${DEPLOY_ROOT}/log
```

## Optional Overrides / 可选配置覆盖

Services use image-bundled defaults unless override files exist under `${DEPLOY_ROOT}/control/overrides`.

默认使用镜像内置配置。只有当 `${DEPLOY_ROOT}/control/overrides` 下存在覆盖文件时，脚本才生成单文件挂载。

Supported override files:

支持的覆盖文件：

```text
${DEPLOY_ROOT}/control/overrides/GW/config/mcpTools.tsv
${DEPLOY_ROOT}/control/overrides/GW/config/apiKeyList.csv
${DEPLOY_ROOT}/control/overrides/GW/config/spring-gw-client.xml
${DEPLOY_ROOT}/control/overrides/GW/config/log4j.ini
${DEPLOY_ROOT}/control/overrides/<Service>/config/log4j.ini
```

After adding a new override file:

新增覆盖文件后：

```bash
bash generate-compose-overrides.sh .env.prod compose.override.generated.yaml
./restart-service.sh <service>
```

## Repository Files / 仓库文件

This repository keeps only the files needed for deployment and maintenance:

本仓库只保留部署和维护所需文件：

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
```
