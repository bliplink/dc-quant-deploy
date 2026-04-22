# 数据库说明

## 部署模式

1. `embedded`
   使用 `compose.yaml` 里的 `clickhouse` 服务，部署脚本自动执行初始化。
2. `external`
   使用已有 ClickHouse，初始化由用户手动执行。

## 初始化目录

- `clickhouse/apply-init.sh`
- `clickhouse/init/00-create-db.sql`
- `clickhouse/init/01-run-all.sh`
- `clickhouse/init/10-schema/`
- `clickhouse/init/20-view/`
- `clickhouse/init/90-optional-seed/`

## 默认初始化

`embedded` 模式会自动执行：

```bash
clickhouse/apply-init.sh
```

顺序：

1. 创建 `dc` 数据库。
2. 执行 `10-schema/`。
3. 执行 `20-view/`。

`90-optional-seed/` 不会自动执行。

`external` 模式需要用户在部署前手动初始化。

## 手动初始化

```bash
./clickhouse/apply-init.sh
```
