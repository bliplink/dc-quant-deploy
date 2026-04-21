# dc-quant-deploy

`dc-quant-deploy` 是 DC 量化交易系统的单机 Docker Compose 部署仓库。

语言：

- English: [README.md](./README.md)
- 简体中文: [README.zh-CN.md](./README.zh-CN.md)

## 这个仓库做什么

它提供两种明确的一键部署方式：

- 从无到有部署：同时部署 DC 应用栈和 ClickHouse 容器。
- 已有数据库部署：继续使用用户已有 ClickHouse，只部署 DC 应用栈。

系统包含：

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

- 只支持单机 Docker Compose。
- 数据库只有 ClickHouse，没有 MySQL。
- 初始化后的运行目录只需要保留 `control/`、`data/`、`log/`。
- `.env.prod`、`control.prod/`、license 和运行数据都不提交 Git。

## 方式一：从无到有部署

适合新服务器，或者没有现成 ClickHouse 的环境。

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

这个入口会启动 `dc-clickhouse` 容器，并自动初始化 `dc` 数据库、表和视图。

## 方式二：已有 ClickHouse 后部署

适合已经有 ClickHouse 的环境。

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

这个入口不会启动 `dc-clickhouse`，也不会自动修改已有 ClickHouse。

## 部署后验证

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml ps
curl -I http://127.0.0.1/web/
printf ruok | nc -w 3 127.0.0.1 2181
```

如果使用内置 ClickHouse：

```bash
curl 'http://127.0.0.1:8123/?query=SELECT%201'
```

如果使用已有 ClickHouse，请按 `.env.prod` 中的地址、用户名和密码验证。

## 日常维护

查看状态：

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml ps
```

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

## 重要文件

- `.env.prod`：本机部署变量，不提交 Git。
- `control.prod/`：本机控制文件，不提交 Git。
- `control.prod/dc.dat`：license 文件，不提交 Git。
- `${DEPLOY_ROOT}/control`：运行时控制文件。
- `${DEPLOY_ROOT}/data`：运行时数据。
- `${DEPLOY_ROOT}/log`：运行时日志。

## 文档

- [用户手册](./docs/user-manual.zh-CN.md)
- [两种一键部署模式](./docs/deployment-modes.zh-CN.md)
- [系统维护手册](./docs/maintenance.zh-CN.md)
- [架构说明](./docs/architecture.zh-CN.md)
- [数据库说明](./docs/database.zh-CN.md)
- [运行时可选覆盖配置](./docs/runtime-overrides.zh-CN.md)
- [发布流程](./docs/release-flow.zh-CN.md)
- [文档索引](./docs/README.zh-CN.md)
