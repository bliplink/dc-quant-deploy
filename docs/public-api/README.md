# Public API documentation deployment

This image publishes an allowlisted subset of `docs/openapi/` and `docs/api/` as a standalone static site. It validates the OpenAPI YAML, generates an English and Chinese 28-method catalog from that YAML, and runs strict MkDocs builds for `/en/` and `/zh/`. Internal deploy notes and evidence are not copied into the build context. The English edition covers core integration guides; the full field-level reference remains in Chinese and is linked explicitly.

Use the reusable entry point from the repository root:

```bash
scripts/update-public-api-docs.sh check --base-ref origin/saas-crypto
# After reviewing matching English/Chinese edits and both release notes:
scripts/update-public-api-docs.sh check --base-ref origin/saas-crypto --accept
scripts/update-public-api-docs.sh build
# Commit and push the checked bilingual sources, then on the deployment host:
scripts/update-public-api-docs.sh deploy
```

`check` verifies paired English/Chinese pages and, with a base ref, rejects one-sided edits. The accepted hash manifest also detects one-sided edits **after** commits are pushed or Actions is unavailable. Changes to published OpenAPI/reference source require both changelog pages before `--accept` can refresh that manifest. This checks parity and review workflow, not whether a human translation is semantically correct. The build generates both method catalogs from the same validated YAML and runs two strict MkDocs builds; the CI workflow repeats these gates when Actions is available. `deploy` requires a clean Git worktree, builds a sha-tagged image, listens on host port `18096`, checks Docker health and both language routes/catalogs/YAML downloads, and preserves the previous container under a timestamped name for rollback. Override `PUBLIC_API_DOCS_TAG` for a candidate build; on a GitHub runner, `PUBLIC_API_DOCS_PYTHON_IMAGE=python:3.12-slim` bypasses the local registry mirror.

The `publish-public-api-docs.yml` workflow runs on `saas-crypto` pushes that touch public API sources (or manual dispatch on that branch). It prepares the same allowlisted context, checks bilingual changes, builds `linux/amd64` and `linux/arm64`, and pushes `ghcr.io/bliplink/opentradingcore-api-docs:sha-<commit>`. **Pushes publish only; deployment requires a manual workflow dispatch.** The deploy job pulls the **digest** produced by that build, switches the local container with rollback, then probes the public hostname. It requires a GitHub self-hosted runner on the Docker host with `self-hosted`, `macOS`, `ARM64`, and custom `otc-api-docs` labels, plus access to the local Docker daemon. Register that runner only for this repository and restrict the `local-api-docs` GitHub environment to the protected `saas-crypto` branch with required reviewers. Do not allow untrusted pull requests to run on this host. The repository currently has no runner, no branch protection and no environment approval; do not enable unattended production deployment until those controls exist. The local `deploy` command remains available meanwhile. The repository's `GITHUB_TOKEN` needs package read/write access for its associated GHCR package.

The Cloudflare Tunnel ingress for `api.opentradingcore.com` should point directly to `http://127.0.0.1:18096`. Route the hostname to the existing tunnel with `cloudflared tunnel route dns <tunnel-UUID> api.opentradingcore.com`, validate the local ingress file, and restart only the tunnel after the container is healthy. The public main site's API menu links directly to this hostname. There is deliberately no `/docs/` reverse proxy on the main site. `/` redirects to `/zh/` only when the leading `Accept-Language` is Chinese; otherwise it redirects to `/en/`. The Material language selector links both editions, while legacy unprefixed reference URLs redirect to the Chinese or English equivalent.

Before declaring success, check the root redirect, `/en/`, `/zh/`, both language selectors, `/en/openapi/CATALOG_GENERATED/`, `/zh/openapi/CATALOG_GENERATED/`, both YAML downloads, and `/healthz` locally and through the public hostname. Confirm both editions still state Developer Preview; a successful docs deployment does not grant External GA status.
