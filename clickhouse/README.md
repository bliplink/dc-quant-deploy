# ClickHouse

This directory contains the public ClickHouse bootstrap assets used by `dc-quant-deploy`.

## Layout

- `init/00-create-db.sql`: create database
- `init/01-run-all.sh`: ordered bootstrap runner
- `init/10-schema/`: core DDL
- `init/20-view/`: view DDL
- `init/90-optional-seed/`: operator-controlled SQL only

## Rule

Only schema and view creation runs automatically.

Optional seed, cleanup, and verification SQL stays manual.
