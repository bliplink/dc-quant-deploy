# MySQL migrations

`deploy-saas.sh` applies every `*.sql` file in lexical order after MySQL is
healthy and before the application services start.

Migration files must be idempotent because they are reapplied on every deploy.
Fresh installations must also receive the equivalent schema and seed changes
in `../init/10-dc.sql`.

- `20260919_open_api_key_policy.sql`: extends tenant-scoped API keys with Open API permissions, IP allowlist, expiry, rate-limit profile, operator label and last-used metadata. Existing trader/Robot keys retain backward-compatible trading defaults; tenant/service keys are normalized to the tenant permission class.
- `20260919_open_api_session_context.sql`: persists API key type, permission scopes and rate-limit profile on LoginSvr sessions. Pre-upgrade API sessions have no permission snapshot and must authenticate again after rollout.
