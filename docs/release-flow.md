# Release Flow

## Standard Rule

Formal releases use image tags.

Do not treat "upload a single jar to the server" as the standard release path for this repository.

## Normal Release Path

1. change application source
2. publish a new image tag from the owning source repository
3. update the corresponding tag in `.env.prod`
4. run `./validate.sh`
5. run `./deploy.sh`

## Image Owners

- `zookeeper` comes from `bliplink/zookeeper`
- `GW` comes from `bliplink/gateway`
- `mdsvr` comes from `bliplink/com.app.dc.mdsvr`
- `apssvr` comes from `bliplink/com.app.dc.apssvr`
- `quantsvr` comes from `bliplink/com.app.dc.quantsvr`
- `indsvr` comes from `bliplink/com.app.dc.indsvr`
- `simsvr` comes from `SKT-Walter/com.app.dc.simulation`
- `batchsvr` comes from `bliplink/com.app.dc.batchsvr`
- `web` comes from `SKT-Walter/com.app.dc.web`

## Emergency Rule

If a one-off emergency workaround requires overriding a jar manually, treat it as a temporary deviation only.

That path is not durable because the next container restart returns to the image version.

## Rollback Rule

Rollback is image-based and control-file-based:

1. stop the current Compose stack
2. restore the previous `control` backup
3. restart the legacy services if the old launcher exists

ClickHouse data is preserved during rollback.
