# MySQL migrations

`deploy-saas.sh` applies every `*.sql` file in lexical order after MySQL is
healthy and before the application services start.

Migration files must be idempotent because they are reapplied on every deploy.
Fresh installations must also receive the equivalent schema and seed changes
in `../init/10-dc.sql`.
