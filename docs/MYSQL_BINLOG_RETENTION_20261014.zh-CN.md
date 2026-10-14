# MySQL binlog 保留期 — 1 天（2026-10-14）

按照用户的要求，Mac mini Demo 上 MySQL 8.0.36 的 `binlog_expire_logs_seconds` 已通过 `SET PERSIST` 调整为 **86400 秒（24 小时）**；`binlog_expire_logs_auto_purge=ON`。持久变量已在 `performance_schema.persisted_variables` 核实，MySQL 未重启。首次执行 `FLUSH BINARY LOGS` 后，MySQL 自己回收了已过期的 binlog.000001 和 binlog.000002。未手工删除 binlog 文件，也未修改数据库中的业务数据。

`compose.yaml` 现在有缺省项 `--binlog-expire-logs-seconds=${MYSQL_BINLOG_EXPIRE_SECONDS:-86400}`，确保未来新建部署也遵循一天保留期。现有 MySQL 容器没有重建，当前由 MySQL 持久化变量使其生效。

注意：该设置限制**可用 binlog 的最长留存范围**；PITR/备份若需恢复超过 24 小时之前的事务，必须事先另行备份。不要从操作系统直接 `rm binlog.*`；MySQL 会在启动或日志轮换时清理已过期文件。
