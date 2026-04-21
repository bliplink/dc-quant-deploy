# dc-quant-deploy

`dc-quant-deploy` 是 DC 量化交易系统的开源部署仓库。

语言：

- English: [README.md](./README.md)
- 简体中文: [README.zh-CN.md](./README.zh-CN.md)

这个仓库面向单机 Docker Compose 部署，目标是在不依赖原始生产机私有目录的前提下，拉起完整运行骨架：

- `zookeeper`
- `gateway` (`GW`)
- `mdsvr`
- `apssvr`
- `quantsvr`
- `indsvr`
- `simsvr`
- `batchsvr`
- `web`
- `clickhouse`

## 范围

- 部署形态：单机 Docker Compose
- 数据库边界：只有 ClickHouse
- 发布模型：版本化镜像
- `GW = gateway`

这个仓库不包含：

- 真实生产密钥
- 真实生产 `control.prod/`

## 仓库结构

- [compose.yaml](./compose.yaml)：主部署拓扑
- [.env.example](./.env.example)：公开部署变量模板
- [deploy.sh](./deploy.sh)：一键部署入口
- [validate.sh](./validate.sh)：部署前校验
- [rollback.sh](./rollback.sh)：回滚入口
- [control.template](./control.template)：占位符版控制模板
- [control.prod.example](./control.prod.example)：去敏的示例控制文件
- [clickhouse](./clickhouse)：ClickHouse 初始化 SQL 与辅助文件
- [docs/architecture.md](./docs/architecture.md)：英文架构说明
- [docs/architecture.zh-CN.md](./docs/architecture.zh-CN.md)：中文架构说明
- [docs/database.md](./docs/database.md)：英文数据库说明
- [docs/database.zh-CN.md](./docs/database.zh-CN.md)：中文数据库说明
- [docs/release-flow.md](./docs/release-flow.md)：英文发布流程
- [docs/release-flow.zh-CN.md](./docs/release-flow.zh-CN.md)：中文发布流程
- [docs/service-cutover.md](./docs/service-cutover.md)：英文逐服务切换说明
- [docs/service-cutover.zh-CN.md](./docs/service-cutover.zh-CN.md)：中文逐服务切换说明

## 快速开始

1. 将 `.env.example` 复制为 `.env.prod`
2. 将 `control.prod.example/` 复制为 `control.prod/`
3. 替换 `control.prod/` 里的占位符
4. 执行 `./validate.sh`
5. 执行 `./deploy.sh`

## ClickHouse 模式

仓库支持两种 ClickHouse 模式。

1. `embedded`
   用户没有现成 ClickHouse 时，`deploy.sh` 会从 `compose.yaml` 启动 ClickHouse 容器，并自动执行初始化脚本。
2. `external`
   用户已经有 ClickHouse 时，数据库初始化由用户自己手动处理。`deploy.sh` 不会启动 ClickHouse 容器，也不会改动现有数据库。

请在 `.env.prod` 中设置：

- `CLICKHOUSE_MODE=embedded` 或 `CLICKHOUSE_MODE=external`
- `CLICKHOUSE_HOST`
- `CLICKHOUSE_HTTP_PORT`
- `CLICKHOUSE_USERNAME`
- `CLICKHOUSE_PASSWORD`

部署脚本会：

1. 校验 Docker 与配置输入
2. 备份当前 `control/`
3. 将 `control.prod/` 同步到 `${DEPLOY_ROOT}/control`
4. 如果旧 `scripts/stop` 存在，则先停旧进程
5. 启动 `zookeeper`
6. 只有在 `CLICKHOUSE_MODE=embedded` 时才启动 `clickhouse`
7. 只有在 `CLICKHOUSE_MODE=embedded` 时才自动执行 ClickHouse 初始化脚本
8. 等待 ClickHouse schema 就绪
9. 启动 Java 服务与 `web`

如果使用 `CLICKHOUSE_MODE=external`，请先手工完成数据库初始化，再执行部署。仓库提供的手工入口是：

- `./clickhouse/apply-init.sh`

## ClickHouse 约定

这个公开部署包只使用 ClickHouse。

默认行为：

- 如有需要先创建 `dc` 数据库
- 从 `clickhouse/init/10-schema/` 初始化核心表
- 从 `clickhouse/init/20-view/` 初始化视图对象
- 不自动执行 `90-optional-seed/`

迁移、清理、校验类 SQL 被刻意放在默认启动路径之外。

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

## 密钥与本地覆盖文件

不要把这些内容提交回 Git：

- `.env.prod`
- `control.prod/`
- `${DEPLOY_ROOT}/control`
- `${DEPLOY_ROOT}/data`
- `${DEPLOY_ROOT}/log`

## 更多文档

- [架构说明](./docs/architecture.zh-CN.md)
- [数据库说明](./docs/database.zh-CN.md)
- [运行时可选覆盖配置](./docs/runtime-overrides.zh-CN.md)
- [发布流程](./docs/release-flow.zh-CN.md)
- [逐服务切换](./docs/service-cutover.zh-CN.md)
- [文档索引](./docs/README.zh-CN.md)

## 运行时可选覆盖配置

默认使用镜像内置配置。只有当宿主机 `${DEPLOY_ROOT}/control/overrides` 下存在指定文件时，部署脚本才会生成 `compose.override.generated.yaml` 并挂载该文件。

支持的覆盖文件：

- `GW/config/mcpTools.tsv`
- `GW/config/apiKeyList.csv`
- `GW/config/spring-gw-client.xml`
- `GW/config/log4j.ini`
- `MDSvr|APSSvr|QuantSvr|INDSvr|SIMSvr|BatchSvr/config/log4j.ini`

`log4j.ini` 通常约 1 秒热生效；`mcpTools.tsv` 与 `apiKeyList.csv` 约 1 分钟内由 GW 自动重载；`spring-gw-client.xml` 修改后需要重启 `gateway` 容器。

初始化后的宿主机运行根目录只需要保留 `control/`、`data/`、`log/`，不要再挂载整个 `${DEPLOY_ROOT}/dc/GW/config`。

## 单服务重启

服务已经完成容器化切换后，可以用同一个入口只重启一个服务，不影响其它容器：

```bash
./restart-service.sh apssvr --dry-run
./restart-service.sh apssvr
```

生产上的 APSSvr 定时重启沿用旧系统 `restartjob.sh` 的时间点：每天 `00:05`。

```cron
5 0 * * * cd /data/strategy/dc-quant-deploy && ./restart-service.sh apssvr >> /data/strategy/log/cron-apssvr-restart.log 2>&1
```

这个脚本使用 `docker compose up -d --no-deps --force-recreate <service>`，不会拉新镜像，也不会启动依赖服务。
