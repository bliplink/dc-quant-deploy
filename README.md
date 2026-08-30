# DC Cryptocurrency SaaS deployment

This branch deploys the standalone cryptocurrency SaaS product. It does not
contain or start QuantSvr, INDSvr, CustomIndSvr, SIMSvr, BatchSvr, or the
quantitative web application.

## Runtime boundary

| Layer | Components | Storage |
| --- | --- | --- |
| Access | dc-trade-web, GW, LoginSvr | MySQL session/user data |
| Market data | APSSvr, MDSvr | ClickHouse K-line data |
| Trading | OrderSvr, TradeSvr, LiqSvr | MySQL orders/trades/balances/positions |
| Management | ManagerSvr, AdminSvr | MySQL configuration and audit data |
| Discovery | ZooKeeper | Dedicated loopback port and data directory |

The tenant key is always `location`. This deployment does not introduce a
parallel `tenant_id`. MySQL holds business transactions; ClickHouse holds only
market/K-line data.

All names, ports, and data paths are isolated from a legacy STC installation:

- Compose project and containers: `dc-saas*`
- Runtime root: `/data/dc-saas-runtime` on the dedicated local data disk
- Web: `18088`
- ZooKeeper: `32181`
- MySQL: `33306` (loopback only)
- ClickHouse: `38123/39000` (loopback only)
- GW: `33000/33001/33002`
- SaaS services: `33028`, `33034-33040`

## One-click deploy

```bash
git clone --branch saas-crypto <dc-quant-deploy-repository> /root/dc-saas-deploy
cd /root/dc-saas-deploy
sudo ./deploy-saas.sh
```

The first run:

1. installs Docker Engine and Compose when absent;
2. creates `.env.prod` with random local passwords;
3. verifies the isolated ports are unused;
4. generates ATS, DB pool, GW, and service configuration;
5. pulls the application images produced from each dedicated `saas-crypto`
   branch on GitHub Container Registry;
6. initializes MySQL and the location-aware ClickHouse K-line schema;
7. starts and validates all 13 containers.

`.env.prod` is runtime-only and must never be committed.

The default `IMAGE_SOURCE=registry` mode pulls public `saas-crypto` images from
GHCR and never uploads or compiles application source on the deployment host.
No GitHub or GHCR login is required. Package visibility is public while the
service source repositories may remain private. The Web image is published as
`ghcr.io/bliplink/dc-saas-trade-web` by this public deployment repository.

`REQUIRE_GHCR_LOGIN` remains available only for operators who replace the
defaults with their own private registry packages. Credentials must be supplied
through the protected runtime environment and must never be committed.

## Validation

```bash
sudo ./validate-saas.sh
sudo ./smoke-test-location.sh
```

The location smoke test inserts temporary rows for two locations into MySQL and
ClickHouse, verifies there is no cross-location match, and removes its test
rows.

Run the complete browser acceptance flow with an operator-supplied test
password. The helper idempotently prepares the two test users, verifies both
logins through the real GW/LoginSvr path, and then covers deposit, limit order,
cancel, matched buy/sell execution, trade history, and recent trades:

```bash
sudo E2E_PASSWORD='replace-with-a-test-password' \
  ./tests/run-web-trading-e2e-host.sh
```

The password is never committed. Its SHA-256 digest is written only to the two
named test users in `WEB_E2E`. The reusable Playwright runner and npm cache make
subsequent checks fast on legacy hosts using Docker's `vfs` storage driver.
The precheck also proves that valid credentials are rejected when the request
uses another `location`.

Run the SaaS control-plane acceptance as root so the generated platform
administrator password remains inside the protected runtime environment:

```bash
sudo ./tests/run-tenant-lifecycle-e2e-host.sh
```

This provisions two uniquely named `*_E2E_*` tenants through the public
application and platform-approval APIs. It verifies dedicated login URLs,
same-name user isolation, tenant-admin RBAC, product settings, trade-record
queries, suspend/reactivate enforcement, audit rows, and database account
initialization. The two acceptance tenants are retained as immutable evidence;
their randomly generated passwords are never printed or committed.

Use the browser variant to execute the same API/database contract and then
verify the English/Chinese desktop and mobile onboarding/administration pages.
It stores screenshots below the protected runtime evidence directory:

```bash
sudo ./tests/run-tenant-lifecycle-web-e2e-host.sh
```

## Automatic public-image deployment

Install the root cron task that checks the public GHCR application tags every
five minutes and deploys a complete, validated SaaS release when they change:

```bash
sudo ./install-auto-update-cron.sh
sudo ./auto-update-saas.sh --force
```

The updater checks remote manifest digests before downloading, waits for one
stable release set, pulls changed application images serially, applies schema
migrations, validates the whole stack, and restores the previous running image
IDs if validation fails. It never updates MySQL, ClickHouse, or ZooKeeper.

## Product documentation

- [中文用户手册](docs/USER_GUIDE.zh-CN.md)
- [对标 Binance / Bybit 的产品化路线图](docs/BINANCE_BYBIT_ROADMAP.zh-CN.md)
- [SaaS 公共镜像自动部署与运维](docs/AUTO_UPDATE.zh-CN.md)

## Uninstall and recovery

Remove containers but preserve databases and generated configuration:

```bash
sudo ./uninstall-saas.sh
```

Permanently remove the isolated SaaS runtime data:

```bash
sudo ./uninstall-saas.sh --purge-data
```

完整清理 SaaS 容器、运行数据、专用构建缓存及这些容器引用的镜像：

```bash
sudo ./uninstall-saas.sh --purge-data --purge-images
```

卸载脚本清理名称前缀 `dc-saas-*`、带 `dc.saas.role` 标签，或明确挂载本仓库测试目录/`/data/dc-saas-runtime` 的验收容器，同时清理 Compose 项目 `dc-saas` 以及 `dc-saas-*` 前缀的网络和卷（包括 Web E2E 缓存卷）；不会选择量化系统、`/opt/dc-runtime` 或 `/opt/sumscope`。

The purge command accepts only the exact
`/data/dc-saas-runtime` or legacy `/opt/dc-saas-runtime` path and never selects
`/opt/dc-runtime` or `/opt/sumscope`. Image purge removes only the exact SaaS
tags and never deletes a shared image ID used by the quantitative stack.

Redeploy with the preserved data by running `sudo ./deploy-saas.sh` again.

## Implementation sequence after deployment

1. Establish a regression baseline for login, market data, order lifecycle,
   execution, liquidation, balances, positions, and two-location isolation.
2. Audit every MySQL DAO and GW handler so all tenant-owned reads and writes
   include `location`; add composite indexes or keys only through versioned
   migrations.
3. Implement exchange-compatible order validation as shared domain rules:
   tick/step size, minimum notional, market/limit/stop orders, reduce-only,
   position mode, leverage, margin, fees, funding, and liquidation.
4. Add idempotency keys, immutable order/trade events, reconciliation jobs,
   ledger invariants, and risk limits before enabling real funds.
5. Add observability, encrypted secret management, backups, restore drills,
   rolling upgrades, and tenant-level rate limits.
6. Promote immutable `sha-*` images through QA and staging before production;
   never deploy the moving quant `latest` tags into this stack.
