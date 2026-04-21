# 两种一键部署模式

`dc-quant-deploy` 提供两种面向用户的一键部署入口。

## 1. 从无到有部署

适用场景：

- 新服务器。
- 没有现成 ClickHouse。
- 希望一条命令部署完整系统。

入口：

```bash
./deploy-standalone.sh
```

推荐准备方式：

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

这个入口会：

- 备份当前 `.env.prod`。
- 设置 `CLICKHOUSE_MODE=embedded`。
- 设置 `CLICKHOUSE_HOST=127.0.0.1`。
- 启动 `dc-clickhouse` 容器。
- 按 `.env.prod` 中的 `CLICKHOUSE_USERNAME` / `CLICKHOUSE_PASSWORD` 初始化容器账号。
- 自动执行 ClickHouse 初始化脚本，初始化脚本通过 native 端口 `CLICKHOUSE_NATIVE_PORT` 连接 ClickHouse。
- 启动 ZooKeeper、Java 服务和 web。

保护规则：

- 如果本机 `8123` 或 `9000` 已经被其它 ClickHouse 或服务占用，脚本会提前失败。
- 已有数据库的生产机不要使用这个入口。

## 2. 已有 ClickHouse 后部署

适用场景：

- 生产机已有 ClickHouse。
- 不希望部署脚本启动 ClickHouse 容器。
- 不希望一键部署改动现有数据库。
- 只希望部署 ZooKeeper、Java 服务和 web。

入口：

```bash
./deploy-with-external-clickhouse.sh
```

推荐准备方式：

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

`.env.prod` 中需要填真实 ClickHouse：

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
- 保留 `.env.prod` 中已有的 ClickHouse 地址、端口、用户名和密码。
- 不启动 `dc-clickhouse`。
- 不自动改动外部 ClickHouse。
- 校验外部 ClickHouse 连通性和核心 schema。
- 启动 ZooKeeper、Java 服务和 web。

如果外部 ClickHouse 还没有初始化，先执行：

```bash
./clickhouse/apply-init.sh
```

默认初始化只建库、建表、建视图，不导入样例数据。

## 3. 怎么选择

| 场景 | 使用入口 | ClickHouse 行为 |
| --- | --- | --- |
| 新机器，没有数据库 | `./deploy-standalone.sh` | 启动 ClickHouse 容器并初始化 |
| 生产已有数据库 | `./deploy-with-external-clickhouse.sh` | 使用现有 ClickHouse，不启动容器 |
| 想演练应用部署但不迁移数据 | `./deploy-with-external-clickhouse.sh` | 继续使用现有 ClickHouse |
| 想验证开源从零安装 | `./deploy-standalone.sh` | 使用内置 ClickHouse |

## 4. 与底层 deploy.sh 的关系

`deploy.sh` 是底层统一部署入口，实际行为由 `.env.prod` 中的 `CLICKHOUSE_MODE` 决定。

两个一键入口只是安全包装：

- `deploy-standalone.sh`：设置 embedded，再调用 `deploy.sh`。
- `deploy-with-external-clickhouse.sh`：设置 external，再调用 `deploy.sh`。

日常推荐用户直接使用这两个入口，不需要手动切换 `CLICKHOUSE_MODE`。
