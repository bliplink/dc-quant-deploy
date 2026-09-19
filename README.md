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
- Trade Web: `18088`
- Platform Web: `18090`
- Tenant Web: `18092`
- ZooKeeper: `32181`
- MySQL: `33306` (loopback only)
- ClickHouse: `38123/39000` (loopback only)
- GW: `33000/33001/33002`
- SaaS services: `33028`, `33034-33040`

## One-click deploy

Clone once:

```bash
git clone --branch saas-crypto <dc-quant-deploy-repository> /root/dc-saas-deploy
cd /root/dc-saas-deploy
```

Install the safe standalone topology:

```bash
sudo ./install-saas.sh
```

Install the complete clustered topology in one command:

```bash
sudo ./install-saas.sh --full-cluster
```

`--full-cluster` deterministically enables MDSvr A/B/C, OrderSvr A/B,
TradeSvr A/B, and ProjectionSvr. Order and Trade use fenced 256-partition
assignments; deployment waits for replication listeners and partition readiness
before reporting success.

### OrderSvr A/B development cutover

The main SaaS stack can run the logical `OrderSvr` on two partitioned physical
nodes while continuing to use the existing LoginSvr, TradeSvr, MDSvr, APSSvr,
LiqSvr, MySQL and ClickHouse services. The switch is deliberately opt-in and
requires GW, OrderSvr, MDSvr, TradeSvr and LiqSvr images that embed the same
cluster-capable `com.app.common` JAR.

Build those immutable images with `build-cluster-dev-ordersvr.sh` (or the
PowerShell equivalent) using `INCLUDE_GATEWAY=true` and
`INCLUDE_CORE_CONSUMERS=true`. Supply the five resulting public GHCR image
references and run:

```bash
sudo -E ./switch-main-order-cluster.sh
```

When the immutable development images were built directly on the validation
host and have not yet been published to GHCR, set
`ORDER_CLUSTER_LOCAL_IMAGES=true`. The switch verifies that all five images
exist locally and invokes the normal deploy flow with `--skip-pull`. Formal
release still requires publishing the shared Maven artifacts and public GHCR
images first.

The switch pauses automatic moving-tag updates, saves the complete standalone
environment under the runtime deploy-state directory, initializes 256 fenced
ZooKeeper partitions, waits until all partitions have recovered, and then runs
the normal SaaS validator. To return to the saved single-node configuration:

```bash
sudo ./rollback-main-order-cluster.sh
```

Rollback removes only the second container; journals and snapshots are retained
for diagnosis.

The first run:

1. installs Docker Engine and Compose when absent;
2. creates `.env.prod` with random local passwords;
3. verifies the isolated ports are unused;
4. generates ATS, DB pool, GW, and service configuration;
5. pulls the application images produced from each dedicated `saas-crypto`
   branch on GitHub Container Registry;
6. initializes MySQL and the location-aware ClickHouse K-line schema;
7. starts and validates the selected topology; `--full-cluster` additionally waits for MD/Order/Trade cluster readiness and ProjectionSvr.

`.env.prod` is runtime-only and must never be committed.

The default `IMAGE_SOURCE=registry` mode pulls public `saas-crypto` images from
GHCR and never uploads or compiles application source on the deployment host.
No GitHub or GHCR login is required. Package visibility is public while the
service source repositories may remain private. The Web image is published as
`ghcr.io/bliplink/dc-saas-trade-web` by this public deployment repository.

Set `IMAGE_SOURCE=local` in `.env.prod` when the single host should build the
application images itself. In this mode `install-saas.sh` calls
`build-saas-images.sh`, uses the dedicated source branches (or a verified
`SOURCE_BUNDLE_PATH`), and pulls only MySQL, ClickHouse, and ZooKeeper from
public registries. An explicit `local` setting is preserved across redeploys.

Private source repositories can be read in three ways: an existing Git credential
helper on the host, a verified `SOURCE_BUNDLE_PATH`, or a token supplied only in
the protected runtime environment as `SOURCE_GIT_TOKEN` (optional
`SOURCE_GIT_USERNAME`, default `x-access-token`). The token is consumed through
a temporary `GIT_ASKPASS` helper and is not embedded in repository URLs or
committed configuration.

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

After a `--full-cluster` installation, run the unified full-business
acceptance:

```bash
sudo ./acceptance-saas.sh
```

The unified command first validates runtime health, creates isolated `*_E2E`
tenant accounts through the real public `AdminSvr.tenantUserRegistration`
path. It also validates tenant application/approval, RBAC, quotas and
tenant lifecycle/isolation through both the Trade Web embedded administration
pages and the standalone Tenant Web (:18092) / Platform Web (:18090). The
standalone console test clicks every currently enabled management operation:
tenant user create/enable/disable/password reset, all trade-query tabs, symbol
toggle/restore, Robot create/edit/enable/disable, tenant info/audit/settings
save-and-restore, application needs-info/reject/approve, tenant configuration
and route save, plus cluster snapshot/placement preview/re-apply. Host-Agent
upgrade buttons are asserted disabled until that feature exists. It then executes browser login,
deposit, limit/market order flows, cancellation, matching, position close,
trade/history checks, partial/final liquidation, insurance fund and ADL
coverage, RobotSvr API-key/liquidity/quote-replenishment behavior, Projection
watermark advancement, TradeSvr A/B role reversal, and a final health
validation. The full acceptance also contains a mandatory bounded pressure
gate. By default it sends 1,000 resting orders followed by mass cancel, 1,000
maker orders and 1,000 taker orders at concurrency 16 through the real
GW -> OrderSvr -> TradeSvr path. The pressure gate validates zero request
failures/rejections, matching and accounting consistency, fees/margins/positions,
unique client order IDs, persisted restart recovery, post-recovery position
close, and no OOM/stopped core containers. TPS plus p50/p95/p99 latency are
written into the pressure evidence and surfaced in `acceptance-summary.json`.
Operators can raise the bounded load with `ACCEPTANCE_STRESS_ORDERS` and
`ACCEPTANCE_STRESS_CONCURRENCY`; the full acceptance never skips this stage.

Each stage writes a log plus `acceptance-summary.json` below
`${DEPLOY_ROOT}/evidence/<run>-full-acceptance/`. Any critical failure makes the
command fail.

The standalone browser acceptance helper now also provisions buyer/seller
identities through the real tenant self-registration path before trading:

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

Current operator/developer documentation:

- [中文用户手册](docs/USER_GUIDE.zh-CN.md)
- [当前实施方案与服务/分支基线](SAAS_IMPLEMENTATION_PLAN.md)
- [SaaS 公共镜像自动部署与运维](docs/AUTO_UPDATE.zh-CN.md)
- [DC Open API v1 文档入口（Trader / Tenant / WebSocket）](docs/openapi/README.zh-CN.md)
- [Trading API v1（Trader/Broker 共用）](docs/openapi/TRADING_API_V1.zh-CN.md)
- [Trader API v1](docs/openapi/TRADER_API_V1.zh-CN.md)
- [Broker API v1](docs/openapi/BROKER_API_V1.zh-CN.md)
- [Tenant Management API v1](docs/openapi/TENANT_API_V1.zh-CN.md)
- [WebSocket / Topic Reference v1](docs/openapi/WEBSOCKET_TOPICS_V1.zh-CN.md)
- [Crypto Open API v1 架构与接口基线](docs/CRYPTO_OPEN_API_V1.zh-CN.md)
- [DC Open API v1 字段级调用参考](docs/DC_OPEN_API_V1_REFERENCE.zh-CN.md)
- [Crypto OpenAPI 3.0 GW HTTP 传输规范](docs/openapi/crypto-openapi-v1.yaml)
- [集群开发期本地 Common/镜像专项流程](docs/CLUSTER_DEV_LOCAL_COMMON_BUILD.zh-CN.md)
- [对标 Binance / Bybit 的产品化路线图](docs/BINANCE_BYBIT_ROADMAP.zh-CN.md)

Historical acceptance evidence (dated snapshots; not current runbooks):

- [产品、业务规则、数据流与验收快照（2026-08-29/09-01）](docs/DC_SAAS_CRYPTO_PRODUCT_AND_ACCEPTANCE_20260829.zh-CN.md)
- [核心交易稳定性、压力与故障恢复（2026-09-01）](docs/CORE_TRADING_STABILITY_AND_STRESS_ACCEPTANCE_20260901.zh-CN.md)
- [多租户控制面生产验收（2026-08-30）](docs/TENANT_CONTROL_PLANE_ACCEPTANCE_20260830.zh-CN.md)
- Word/PDF 等导出报告同样属于其生成日期的历史快照；当前操作以 README、用户手册和可执行脚本为准。

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

Redeploy with preserved data by running `sudo ./install-saas.sh` again, or `sudo ./install-saas.sh --full-cluster` to restore the complete clustered topology. `install-saas.sh` is a stable operator wrapper around `deploy-saas.sh`, so install and redeploy use the same implementation.

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
