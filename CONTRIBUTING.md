# Contributing

Thanks for helping improve the DC cryptocurrency SaaS deployment.

## Scope

This branch is for deployment, operations, and user-facing documentation of
the standalone DC cryptocurrency SaaS product. Quantitative-service definitions,
business service source code, private production configuration, and runtime
data should not be added here.

## Before Opening A Pull Request

- Do not commit `.env.prod`.
- Do not commit real API keys, Telegram tokens, exchange keys, ClickHouse passwords, or production data.
- Keep example values as placeholders such as `replace-with-*`, `change-me`, or `example-*`.
- For script/config changes, run the same static checks as CI (at minimum `bash -n` on changed shell scripts and `./tests/test-auto-update-saas.sh`). `validate-saas.sh` is a live-stack validator and should be run on an installed host, not treated as a checkout-only command.
- Update the relevant documentation under `docs/` when changing user-visible behavior.
- Changes to install, topology, Tenant/Platform Web, business flows, pressure gates, failover, or recovery must keep `README.md`, `docs/USER_GUIDE.zh-CN.md`, `SAAS_IMPLEMENTATION_PLAN.md`, and `acceptance-saas.sh` consistent.

## Documentation Style

- Chinese docs live under `docs/*.zh-CN.md`.
- Keep README files as navigation entry points.
- Prefer practical "what to do after deployment" instructions over internal implementation detail.

## Pull Request Checklist

- The change contains no secrets.
- The change is reproducible from a clean checkout.
- The change explains any required configuration update.
- The change has been tested or has a clear validation path.
