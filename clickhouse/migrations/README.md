# ClickHouse migrations

These migrations are **not** automatically executed by `deploy-saas.sh`.
The standard SaaS deployment runs `LoginSvr` with `dbType=mysql`; ClickHouse
is used for market/time-series storage.

Use a migration here only for an installation that explicitly configures
`LoginSvr` with `dbType=clickhouse`.

- `20260919_open_api_auth_context.sql`: adds tenant location and Open API key
  policy/session authorization fields required by the `saas-crypto`
  LoginSvr. Existing legacy keys whose `location` is empty must be reissued
  or repaired explicitly; tenant location must not be inferred from
  `user_id`.
