# API Docs + cross-site language synchronization — Demo acceptance (2026-10-20)

## Confirmed behavior

All **four** public-facing OTC applications share the `otc_language` preference:

1. Public homepage: `https://opentradingcore.com/`
2. Trading terminal: `https://trade.opentradingcore.com/`
3. Tenant console: `https://tenant.opentradingcore.com/`
4. Developer API Docs: `https://api.opentradingcore.com/{en,zh}/`

Supported locale values are `en` and `zh-CN`; **English** is the default.
The preference is one-year, non-sensitive, JS-readable cookie with
`Domain=.opentradingcore.com; Path=/; Secure; SameSite=Lax` on HTTPS.
On local Demo host the cookie is host-only and still works across different
localhost ports. Legacy frontend storage keys remain mirrored:
`otc.lang` (`zh-CN`), `dc-trade-language` (`zh`), `otc.tenant.lang` (`zh`).

Setting language in any site updates the cookie; a newly opened sister site
reads it before initialization. Already-open tabs check shared state on
focus/pageshow; the original Tenant Web runtime uses a focused-page refresh
for external changes to avoid rewriting its existing JavaScript bundle.
API Docs switches the same topic between `/en/` and `/zh/` if it exists;
otherwise redirects to the locale root.

## API reference corrections and additions

- Updated the bilingual, **single-page, category-navigated** developer API
  reference from the reviewed OpenAPI schema; no tenant-administration API
  was exposed as a public trading operation.
- Added `BTC003USDT` as a **tenant-defined trading product** and `CUSTOM_BTC`
  as an **independently named single current price source**. Source selection
  requires explicit tenant binding; no ACTIVATE step or automatic old-source
  fallback. No 1% deviation cap. Prices must pass source timestamp/TTL checks.
- Corrected `APSSvr.publishBrokerPrice` from the stale “disabled in Demo”
  text to the observed real Demo acceptance. Source ID may be expressed as
  preferred `data_source_id` (or legacy `security_id` as a source ID), with
  `index_price`, `mark_price`, `source_time_ms`, `ttl_ms`, positive
  `config_version`, and increasing `sequence`.
- Kept Trader API key scope separate from Broker `TenantAPI` scope.
  Trading and historical execution queries use OrderSvr and **AdminSvr**
  respectively. Trade account queries require the top-level Gateway tenant
  routing key even when their body is `{}`.
- Added `TradeSvr.cashIn` and `cashOut` to the **Broker scoped Demo** contract
  with `CUSTOMER_CASH` permission; these are **simulated funds**, not external
  money transfers, and must remain within the signed-in tenant/customer.
- API docs schema: **17** methods; **16** externally displayed operational
  methods in each of EN/ZH, excluding signed-login implementation detail.

## Build and live acceptance

- One reviewed schema passed `openapi_spec_validator` and the catalog gate;
  both MkDocs en/zh strict builds passed. The standard image-builder attempt
  failed because Docker daemon DNS could not resolve its base image mirror;
  the same MkDocs build was run on the authorized host and the generated
  static files were layered over the existing local docs image. Its existing
  SDK wheel and nginx config were retained.
- Main static assets and a trade webpack **production build** succeeded.
  Tenant Vite production build succeeded; the current Demo tenant image kept
  its prior price/TTL UI bundle, with only the small compatibility script and
  HTML boot hook layered on top. Source-native React synchronization is also
  committed for its next ordinary full-image build.
- Chrome cross-app regression (main → trade → tenant → docs, tenant → docs,
  trade → docs, docs → main) **passed at 1440px desktop and 390px mobile**:
  `python3 tests/test-frontend-shared-language-live.py [--mobile]`.
- Real **HTTPS subdomain** browser test passed, including a shared cookie
  scoped to `.opentradingcore.com` (`Secure`, `SameSite=Lax`), with a fresh
  `https://api.opentradingcore.com/en/` redirecting to `/zh/` after choosing
  Chinese on the public homepage.
- Each published frontend served `/healthz` and the shared-language script.

## Running local images

| Service | Demo image |
| --- | --- |
| Main/public-web | `local/dc-saas-public-web:shared-language-20261020` |
| Trade/web | `local/dc-saas-trade-web:shared-language-20261020` |
| Tenant/tenant-web | `local/dc-saas-tenant-web:shared-language-20261020` |
| API Docs/api-docs | `local/dc-saas-api-docs:custom-price-shared-language-20261020` |

Keep `config/frontend-language-rollout-20261020.yaml` as the **last** Compose
`-f` when redeploying these four services on this local Demo. Local tags are
not GHCR-published and must not be assumed available on another machine.

## Source commits (local, not pushed to GitHub)

- `opentradingcore-web`: `7cecffa`
- `dc-trade-web`: `0ee2d30`
- `dc-saas-tenant-web`: `402b4ba`
- `opentradingcore-api-docs`: `692b22a`

This task did **not** modify Trade/Common cluster behavior, fault-inject HA,
use GitHub Actions, access the user's Documents folder or reset tenant data.
