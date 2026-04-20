# web Release Checklist

Use this checklist before changing `WEB_TAG`.

## Build Source

- Confirm the source repository is `SKT-Walter/com.app.dc.web`
- Confirm the target image is `ghcr.io/SKT-Walter/web`
- Confirm the image tag you want already exists in GHCR

## Rebuild Triggers

Rebuild the `web` image when any of these changed:

- frontend source code
- Vite base path or output behavior
- Nginx config
- frontend gateway URL strategy
- frontend Dockerfile

## No-Rebuild Cases

Do not rebuild the `web` image when only these changed:

- Java service image tags
- ZooKeeper image packaging
- `control.prod/`
- backend-only runtime configuration

## Rollout

1. Publish the needed `web` image from `SKT-Walter/com.app.dc.web`
2. Update `WEB_TAG` in `.env.prod`
3. Run `./deploy.sh`
4. Verify `/web/` is reachable through the gateway path
