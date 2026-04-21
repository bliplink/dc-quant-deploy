# dc-quant-deploy

`dc-quant-deploy` 是 DC 量化交易系统的开源部署仓库，面向单机 Docker Compose 部署。

语言：

- English: [README.md](./README.md)
- 简体中文: [README.zh-CN.md](./README.zh-CN.md)

## 项目定位

这个仓库用于在一台服务器上拉起完整 DC Quant 运行骨架：

- `zookeeper`
- `gateway` / `GW`
- `mdsvr`
- `apssvr`
- `quantsvr`
- `indsvr`
- `simsvr`
- `batchsvr`
- `web`
- `clickhouse`

核心约定：

- 部署形态：单机 Docker Compose。
- 数据库边界：只有 ClickHouse，没有 MySQL。
- 发布模型：版本化容器镜像。
- `GW = gateway`。
- 初始化后的运行目录只需要保留 `control/`、`data/`、`log/`。

这个仓库不包含真实生产密钥，也不包含真实生产 `control.prod/`。

## 快速开始

完整安装、验证和运维说明请先阅读：[用户手册](./docs/user-manual.zh-CN.md)。

最短路径：

```bash
git clone https://github.com/bliplink/dc-quant-deploy.git
cd dc-quant-deploy
cp .env.example .env.prod
cp -a control.prod.example control.prod
vi .env.prod
vi control.prod/ATSConfig.ini
vi control.prod/DBPoolConfig.ini
vi control.prod/jaas.ini
cp /path/to/dc.dat control.prod/dc.dat
./validate.sh
./deploy.sh
```

部署后查看状态：

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml ps
```

## 仓库结构

- [compose.yaml](./compose.yaml)：主部署拓扑。
- [.env.example](./.env.example)：公开部署变量模板。
- [deploy.sh](./deploy.sh)：一键部署入口。
- [validate.sh](./validate.sh)：部署前校验。
- [rollback.sh](./rollback.sh)：全量回滚入口。
- [deploy-service.sh](./deploy-service.sh)：逐服务切换入口。
- [rollback-service.sh](./rollback-service.sh)：逐服务回滚入口。
- [restart-service.sh](./restart-service.sh)：单服务容器重启入口。
- [control.template](./control.template)：占位符版控制模板。
- [control.prod.example](./control.prod.example)：脱敏示例控制文件。
- [clickhouse](./clickhouse)：ClickHouse 初始化 SQL 与辅助脚本。
- [docs/user-manual.zh-CN.md](./docs/user-manual.zh-CN.md)：完整用户手册。
- [docs/architecture.zh-CN.md](./docs/architecture.zh-CN.md)：架构说明。
- [docs/database.zh-CN.md](./docs/database.zh-CN.md)：数据库说明。
- [docs/runtime-overrides.zh-CN.md](./docs/runtime-overrides.zh-CN.md)：运行时可选覆盖配置。
- [docs/release-flow.zh-CN.md](./docs/release-flow.zh-CN.md)：发布流程。
- [docs/codex-dev-release.zh-CN.md](./docs/codex-dev-release.zh-CN.md)：Codex 开发、发布与自动部署协作手册。
- [docs/service-cutover.zh-CN.md](./docs/service-cutover.zh-CN.md)：逐服务切换。

## ClickHouse 模式

仓库支持两种 ClickHouse 模式。

1. `embedded`
   用户没有现成 ClickHouse 时，`deploy.sh` 会启动 ClickHouse 容器，并自动执行初始化脚本。
2. `external`
   用户已有 ClickHouse 时，部署脚本不会启动 ClickHouse，也不会自动改库；用户自行初始化。

配置入口在 `.env.prod`：

```dotenv
CLICKHOUSE_MODE=embedded
CLICKHOUSE_IMAGE_TAG=25.9.3.48
CLICKHOUSE_DB_NAME=dc
CLICKHOUSE_HOST=127.0.0.1
CLICKHOUSE_HTTP_PORT=8123
CLICKHOUSE_NATIVE_PORT=9000
CLICKHOUSE_USERNAME=default
CLICKHOUSE_PASSWORD=
```

如果使用外置 ClickHouse，可以手动执行初始化：

```bash
./clickhouse/apply-init.sh
```

默认初始化只建库、建表、建视图，不自动注入样例或迁移种子数据。

## 镜像

- `ghcr.io/bliplink/zookeeper:${ZOOKEEPER_TAG}`
- `ghcr.io/bliplink/gw:${GW_TAG}`
- `ghcr.io/bliplink/mdsvr:${MDSVR_TAG}`
- `ghcr.io/bliplink/apssvr:${APSSVR_TAG}`
- `ghcr.io/bliplink/quantsvr:${QUANTSVR_TAG}`
- `ghcr.io/bliplink/indsvr:${INDSVR_TAG}`
- `ghcr.io/SKT-Walter/simsvr:${SIMSVR_TAG}`
- `ghcr.io/bliplink/batchsvr:${BATCHSVR_TAG}`
- `ghcr.io/SKT-Walter/web:${WEB_TAG}`
- `clickhouse/clickhouse-server:${CLICKHOUSE_IMAGE_TAG}`

如果镜像仓库需要认证：

```bash
docker login ghcr.io
```

并在 `.env.prod` 中设置：

```dotenv
REQUIRE_GHCR_LOGIN=true
```

## 敏感文件

不要提交这些内容：

- `.env.prod`
- `control.prod/`
- `${DEPLOY_ROOT}/control`
- `${DEPLOY_ROOT}/data`
- `${DEPLOY_ROOT}/log`

`dc.dat` 是 license 文件，属于本地实例文件。

## 日常运维

重启单个服务：

```bash
./restart-service.sh apssvr
```

停止单个服务：

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml stop apssvr
```

启动单个服务：

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml up -d --no-deps apssvr
```

查看日志：

```bash
docker logs dc-apssvr --tail 200
tail -n 100 ${DEPLOY_ROOT}/log/APSSvr.log
```

## 运行时可选覆盖配置

默认使用镜像内置配置。只有当宿主机 `${DEPLOY_ROOT}/control/overrides` 下存在指定文件时，部署脚本才会生成单文件挂载。

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

新增覆盖文件后，重启对应服务一次：

```bash
./restart-service.sh apssvr
```

## 文档

- [用户手册](./docs/user-manual.zh-CN.md)
- [架构说明](./docs/architecture.zh-CN.md)
- [数据库说明](./docs/database.zh-CN.md)
- [运行时可选覆盖配置](./docs/runtime-overrides.zh-CN.md)
- [发布流程](./docs/release-flow.zh-CN.md)
- [Codex 开发、发布与自动部署协作手册](./docs/codex-dev-release.zh-CN.md)
- [逐服务切换](./docs/service-cutover.zh-CN.md)
- [文档索引](./docs/README.zh-CN.md)
