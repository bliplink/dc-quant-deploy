# 两种一键部署模式

`dc-quant-deploy` 提供两个明确的部署入口。用户只需要根据是否已有 ClickHouse 选择其中一个。

## 1. 从无到有部署

适用场景：

- 新服务器。
- 没有现成 ClickHouse。
- 希望部署脚本同时拉起数据库和应用栈。

执行：

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

这个入口会：

- 备份当前 `.env.prod`。
- 设置 `CLICKHOUSE_MODE=embedded`。
- 使用 `CLICKHOUSE_HOST=127.0.0.1`。
- 启动 `dc-clickhouse` 容器。
- 按 `.env.prod` 中的 `CLICKHOUSE_USERNAME` 和 `CLICKHOUSE_PASSWORD` 初始化 ClickHouse 用户。
- 通过 native 端口 `CLICKHOUSE_NATIVE_PORT` 执行初始化 SQL。
- 启动 ZooKeeper、Java 服务和 web。

注意：

- 该模式会占用 `8123` 和 `9000`。
- 如果服务器上已有 ClickHouse，请不要使用该模式。
- 默认初始化只建库、建表、建视图，不导入样例数据。

## 2. 已有 ClickHouse 后部署

适用场景：

- 服务器已有 ClickHouse。
- 不希望部署脚本启动 ClickHouse 容器。
- 不希望部署脚本自动修改已有数据库。
- 只需要部署 DC 应用服务、ZooKeeper 和 web。

执行：

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

`.env.prod` 中需要配置真实 ClickHouse：

```dotenv
CLICKHOUSE_MODE=external
CLICKHOUSE_HOST=<your-clickhouse-host>
CLICKHOUSE_HTTP_PORT=8123
CLICKHOUSE_NATIVE_PORT=9000
CLICKHOUSE_DB_NAME=dc
CLICKHOUSE_USERNAME=default
CLICKHOUSE_PASSWORD=<your-password>
```

这个入口会：

- 备份当前 `.env.prod`。
- 设置 `CLICKHOUSE_MODE=external`。
- 保留 `.env.prod` 中的 ClickHouse 地址、端口、用户名和密码。
- 不启动 `dc-clickhouse`。
- 校验外部 ClickHouse 连通性和核心 schema。
- 启动 ZooKeeper、Java 服务和 web。

如果外部 ClickHouse 还没有初始化，可以手动执行：

```bash
./clickhouse/apply-init.sh
```

## 3. 如何选择

| 场景 | 使用入口 | ClickHouse 行为 |
| --- | --- | --- |
| 新机器，没有数据库 | `./deploy-standalone.sh` | 启动并初始化 `dc-clickhouse` |
| 已经有 ClickHouse | `./deploy-with-external-clickhouse.sh` | 使用现有 ClickHouse |
| 只想部署应用，不迁移数据 | `./deploy-with-external-clickhouse.sh` | 使用现有 ClickHouse |
| 验证从零安装流程 | `./deploy-standalone.sh` | 使用内置 ClickHouse |

## 4. 与 deploy.sh 的关系

`deploy.sh` 是底层统一部署入口，实际行为由 `.env.prod` 中的 `CLICKHOUSE_MODE` 决定。

推荐用户直接使用：

- `deploy-standalone.sh`
- `deploy-with-external-clickhouse.sh`

不要手动频繁切换 `CLICKHOUSE_MODE`，避免选错数据库模式。
