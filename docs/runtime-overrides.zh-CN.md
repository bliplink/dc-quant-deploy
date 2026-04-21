# 运行时可选覆盖配置

部署默认使用镜像内置配置。只有当宿主机文件已经存在于 `${DEPLOY_ROOT}/control/overrides` 下时，脚本才会把它挂载到容器里覆盖镜像默认文件。

## 支持的文件

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

不要再挂载整个 GW config 目录，只按上面的单文件覆盖。

## 自动生成 compose override

以下脚本运行前会生成 `compose.override.generated.yaml`：

- `deploy.sh`
- `deploy-service.sh`
- `rollback.sh`
- `rollback-service.sh`
- `validate.sh`

如果某个覆盖文件不存在，就不会生成对应挂载。这样可以避免 Docker 把不存在的宿主机文件路径创建成目录，从而遮挡镜像内默认配置。

## 生效规则

- `log4j.ini` 由 Java 服务监听，通常约 1 秒内热生效。
- `mcpTools.tsv` 由 GW 周期加载，约 1 分钟内生效。
- `apiKeyList.csv` 由 GW 周期加载，约 1 分钟内生效。
- `spring-gw-client.xml` 是 Spring 启动配置，修改后需要重启 `gateway` 容器。

如果容器启动后才首次创建某个覆盖文件，需要先重新生成 compose override 并重建对应服务一次；之后继续修改该文件才按上述热加载规则生效。
