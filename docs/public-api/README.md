# Public API documentation deployment

This image publishes an allowlisted subset of `docs/openapi/` and `docs/api/` as a standalone static site. It validates the OpenAPI YAML, generates a 28-method catalog from that YAML, and runs a strict MkDocs build. Internal deploy notes and evidence are not copied into the build context.

On the host, run `scripts/build-public-api-docs-image.sh` and `scripts/deploy-public-api-docs-host.sh`. The latter listens on host port `18096`, waits for Docker health and HTTP `/healthz`, and preserves the previous container under a timestamped name for rollback. The image tag defaults to `local/opentradingcore-api-docs:sha-<HEAD12>`; override `PUBLIC_API_DOCS_TAG` for a candidate build.

The Cloudflare Tunnel ingress for `api.opentradingcore.com` should point directly to `http://127.0.0.1:18096`. Route the hostname to the existing tunnel with `cloudflared tunnel route dns <tunnel-UUID> api.opentradingcore.com`, validate the local ingress file, and restart only the tunnel after the container is healthy. The public main site links directly to this hostname. There is deliberately no `/docs/` reverse proxy on the main site.

Before declaring success, check `/`, `/openapi/crypto-openapi-v1.yaml`, `/openapi/CATALOG_GENERATED/`, and `/healthz` locally and through the public hostname. Confirm the page still states Developer Preview; a successful docs deployment does not grant External GA status.
