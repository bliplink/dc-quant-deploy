-- Optional LoginSvr ClickHouse storage migration.
-- SaaS deployment currently runs LoginSvr with dbType=mysql, so this file is
-- intentionally NOT auto-applied by deploy-saas.sh.
--
-- Apply only when LoginSvr is explicitly configured with dbType=clickhouse and
-- dc.dc_users_api / dc.dc_users_session already exist.
--
-- Existing legacy API keys may have no tenant location snapshot. Do not infer
-- location from user_id in a multi-tenant deployment; reissue or explicitly
-- repair those keys before enabling Open API authentication.

ALTER TABLE dc.dc_users_api
    ADD COLUMN IF NOT EXISTS location String DEFAULT '',
    ADD COLUMN IF NOT EXISTS permissions String DEFAULT '',
    ADD COLUMN IF NOT EXISTS ip_whitelist Nullable(String),
    ADD COLUMN IF NOT EXISTS expires_at Nullable(String),
    ADD COLUMN IF NOT EXISTS rate_limit_profile String DEFAULT '',
    ADD COLUMN IF NOT EXISTS label Nullable(String),
    ADD COLUMN IF NOT EXISTS last_used_time Nullable(String);

ALTER TABLE dc.dc_users_session
    ADD COLUMN IF NOT EXISTS api_key_type Nullable(String),
    ADD COLUMN IF NOT EXISTS permissions Nullable(String),
    ADD COLUMN IF NOT EXISTS rate_limit_profile Nullable(String);

-- Empty permissions/profile are intentional. LoginSvr normalizes them by API
-- key type on bootstrap:
--   trader -> MARKET_READ,ACCOUNT_READ,ORDER_READ,ORDER_WRITE / TRADER_STANDARD
--   tenant/service -> MARKET_READ,TENANT_READ,TENANT_WRITE / TENANT_STANDARD
