# Optional runtime overrides

Files under this directory are examples only. `deploy.sh` does not copy
`control.prod/overrides` into the runtime control directory by default.

To override an image-bundled config on a server, place the file directly under:

`$DEPLOY_ROOT/control/overrides/<Service>/config/<file>`

Only files that exist on the server are added to `compose.override.generated.yaml`.
