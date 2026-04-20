# web Image

`web` is a required image in this deployment package.

## Runtime Image

- Compose uses: `ghcr.io/SKT-Walter/web:${WEB_TAG}`
- The container serves the frontend with Nginx
- The frontend entry remains `/web/`

## Source Of Truth

The source repository and image pipeline for `web` are not maintained in this repository.

Use the existing published frontend image pipeline as the build source of truth:

- repository: `SKT-Walter/com.app.dc.web`
- published image: `ghcr.io/SKT-Walter/web`

## When You Need A New web Image

Rebuild and republish the `web` image when any of the following changes:

- frontend source code
- Vite build output behavior
- Nginx config
- frontend gateway URL strategy
- Dockerfile used by the web repository

## When You Do Not Need A New web Image

You do not need to rebuild the `web` image when only these change:

- Java service image tags
- ZooKeeper packaging
- `control.prod/`
- backend runtime configuration that does not affect frontend build artifacts

## Deployment Rule

For a normal rollout:

1. Publish the needed `web` image tag first
2. Update `WEB_TAG` in `.env.prod`
3. Run `./deploy.sh`

For a quicker handoff, use `release-checklist.md` before the tag change.
