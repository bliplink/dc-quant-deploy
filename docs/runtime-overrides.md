# Runtime Overrides

The deployment defaults to image-bundled configuration. Host files are mounted only when they already exist under `${DEPLOY_ROOT}/control/overrides`.

## Supported Files

- `${DEPLOY_ROOT}/control/overrides/GW/config/mcpTools.tsv`
- `${DEPLOY_ROOT}/control/overrides/GW/config/apiKeyList.csv`
- `${DEPLOY_ROOT}/control/overrides/GW/config/spring-gw-client.xml`
- `${DEPLOY_ROOT}/control/overrides/GW/config/log4j.ini`
- `${DEPLOY_ROOT}/control/overrides/MDSvr/config/log4j.ini`
- `${DEPLOY_ROOT}/control/overrides/APSSvr/config/log4j.ini`
- `${DEPLOY_ROOT}/control/overrides/QuantSvr/config/log4j.ini`
- `${DEPLOY_ROOT}/control/overrides/INDSvr/config/log4j.ini`
- `${DEPLOY_ROOT}/control/overrides/SIMSvr/config/log4j.ini`
- `${DEPLOY_ROOT}/control/overrides/BatchSvr/config/log4j.ini`

Do not mount the whole GW config directory. Use the supported single-file overrides above.

## Generated Compose Override

The scripts generate `compose.override.generated.yaml` before running Docker Compose:

- `deploy.sh`
- `rollback.sh`
- `validate.sh`
- `restart-service.sh`

If an override file is missing, it is not mounted. This avoids Docker creating an empty host directory that would hide the image-bundled default file.

## Reload Behavior

- `log4j.ini` is watched by the Java services and usually applies in about 1 second.
- `mcpTools.tsv` is reloaded by GW about once per minute.
- `apiKeyList.csv` is reloaded by GW about once per minute.
- `spring-gw-client.xml` is loaded by Spring at startup, so a `GW` restart is required.

If a file is created after the container is already running, regenerate the compose override and recreate the target service once. Later edits follow the reload behavior above.
