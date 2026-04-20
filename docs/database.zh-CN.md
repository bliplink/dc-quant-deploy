# 数据库说明

## 边界

公开部署只使用 ClickHouse。

- 这个仓库里没有 MySQL
- Java 服务只应连接 ClickHouse
- 两套 `DBPoolConfig.ini` 模板都只保留 ClickHouse 配置

## 部署模式

仓库支持两种 ClickHouse 模式：

1. `embedded`
   用户没有现成 ClickHouse 时，直接使用 `compose.yaml` 里的 `clickhouse` 服务，部署脚本会自动执行初始化。
2. `external`
   用户已经有 ClickHouse 时，数据库初始化由用户自己手动处理，部署脚本不会改动现有数据库。

模式由 `.env.prod` 控制：

- `CLICKHOUSE_MODE`
- `CLICKHOUSE_HOST`
- `CLICKHOUSE_HTTP_PORT`
- `CLICKHOUSE_USERNAME`
- `CLICKHOUSE_PASSWORD`

## 初始化目录

- `clickhouse/apply-init.sh`
- `clickhouse/init/00-create-db.sql`
- `clickhouse/init/01-run-all.sh`
- `clickhouse/init/10-schema/`
- `clickhouse/init/20-view/`
- `clickhouse/init/90-optional-seed/`

## 默认初始化行为

只有 `embedded` 模式会自动初始化。

在这个模式下，`deploy.sh` 会调用：

- `clickhouse/apply-init.sh`

这个入口再执行：

- `clickhouse/init/01-run-all.sh`

初始化顺序是：

1. 如有需要创建 `dc` 数据库
2. 执行 `10-schema/` 下全部 SQL
3. 执行 `20-view/` 下全部 SQL

`90-optional-seed/` 下的文件不会自动执行。

如果是 `external` 模式，则需要用户在部署前手工完成初始化。

## 核心 Schema

默认 schema 集包含以下对象：

- `signal`
- `quant_*`
- `kline`
- `backtest_*`
- `strategy_*`

部署校验使用这些核心表作为 readiness 基准：

- `dc.signal`
- `dc.quant_order`
- `dc.strategy_candidate`

## 可选 SQL

以下文件只保留给运维或人工执行：

- `builtin_migration_seed_20260402.sql`
- `reset_all_except_kline_20260419.sql`
- `source_aware_builtin_checks.sql`
- `source_aware_builtin_cleanup.sql`
- `source_aware_checks.sql`
- `source_aware_cleanup_stale_backtest_task_20260411.sql`
- `source_aware_sample_cleanup.sql`

它们不适合放进默认自动初始化，因为里面包含迁移、清理、校验或环境相关逻辑。

## 幂等规则

仓库默认要求初始化 SQL 可重复执行。

当前约定：

- `CREATE DATABASE IF NOT EXISTS`
- `CREATE TABLE IF NOT EXISTS`
- `CREATE VIEW IF NOT EXISTS`

后续新增 DDL 时也应保持同样规则，保证初始化流程可重复跑。

## 手工重跑

如果需要手工重跑默认 schema 初始化：

```bash
./clickhouse/apply-init.sh
```
