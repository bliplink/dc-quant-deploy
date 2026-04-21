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

## 两种一键部署

### 1. 从无到有部署

适用于新机器、没有现成 ClickHouse 的场景：

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
```

这个入口会启动 `dc-clickhouse` 容器并自动初始化数据库。

### 2. 已有 ClickHouse 后部署

适用于生产机已有 ClickHouse、不做数据迁移的场景：

```bash
git clone https://github.com/bliplink/dc-quant-deploy.git
cd dc-quant-deploy
cp .env.external-clickhouse.example .env.prod
cp -a control.prod.example control.prod
vi .env.prod
vi control.prod/ATSConfig.ini
vi control.prod/DBPoolConfig.ini
vi control.prod/jaas.ini
cp /path/to/dc.dat control.prod/dc.dat
./deploy-with-external-clickhouse.sh
```

这个入口不会启动 `dc-clickhouse`，也不会自动修改现有 ClickHouse。

详细说明见：[两种一键部署模式](./docs/deployment-modes.zh-CN.md)。

部署后查看状态：

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml ps
```

## 仓库结构

- [compose.yaml](./compose.yaml)：主部署拓扑。
- [.env.example](./.env.example)：通用部署变量模板。
- [.env.standalone.example](./.env.standalone.example)：从无到有部署模板。
- [.env.external-clickhouse.example](./.env.external-clickhouse.example)：已有 ClickHouse 部署模板。
- [deploy.sh](./deploy.sh)：底层统一部署入口。
- [deploy-standalone.sh](./deploy-standalone.sh)：从无到有一键部署。
- [deploy-with-external-clickhouse.sh](./deploy-with-external-clickhouse.sh)：已有 ClickHouse 后一键部署。
- [validate.sh](./validate.sh)：部署前校验。
- [rollback.sh](./rollback.sh)：全量回滚入口。
- [deploy-service.sh](./deploy-service.sh)：逐服务切换入口。
- [rollback-service.sh](./rollback-service.sh)：逐服务回滚入口。
- [restart-service.sh](./restart-service.sh)：单服务容器重启入口。
- [control.template](./control.template)：占位符版控制模板。
- [control.prod.example](./control.prod.example)：脱敏示例控制文件。
- [clickhouse](./clickhouse)：ClickHouse 初始化 SQL 与辅助脚本。

## ClickHouse 模式

仓库支持两种 ClickHouse 模式：

- `embedded`：没有现成 ClickHouse，使用 `./deploy-standalone.sh`。
- `external`：已有 ClickHouse，使用 `./deploy-with-external-clickhouse.sh`。

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

## 文档

- [用户手册](./docs/user-manual.zh-CN.md)
- [两种一键部署模式](./docs/deployment-modes.zh-CN.md)
- [架构说明](./docs/architecture.zh-CN.md)
- [数据库说明](./docs/database.zh-CN.md)
- [运行时可选覆盖配置](./docs/runtime-overrides.zh-CN.md)
- [发布流程](./docs/release-flow.zh-CN.md)
- [Codex 开发、发布与自动部署协作手册](./docs/codex-dev-release.zh-CN.md)
- [逐服务切换](./docs/service-cutover.zh-CN.md)
- [文档索引](./docs/README.zh-CN.md)
