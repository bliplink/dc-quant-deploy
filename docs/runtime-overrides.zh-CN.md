# 运行时可选覆盖配置

默认情况下，服务使用镜像内置配置。只有当宿主机上的覆盖文件已经存在时，部署脚本才会生成对应的单文件挂载。

覆盖目录固定为：

```text
${DEPLOY_ROOT}/control/overrides
```

## 支持的覆盖文件

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

不要挂载整个 GW config 目录，只使用上面的单文件覆盖方式。

## 自动生成 compose override

这些脚本运行前会生成 `compose.override.generated.yaml`：

- `deploy.sh`
- `rollback.sh`
- `validate.sh`
- `restart-service.sh`

如果覆盖文件不存在，就不会生成对应挂载。这样可以避免 Docker 把不存在的宿主机文件路径创建成目录，从而遮挡镜像内默认配置。

## 生效规则

- `log4j.ini` 通常由 Java 服务监听，修改后约 1 秒内生效。
- `mcpTools.tsv` 由 GW 周期加载，约 1 分钟内生效。
- `apiKeyList.csv` 由 GW 周期加载，约 1 分钟内生效。
- `spring-gw-client.xml` 是 Spring 启动配置，修改后需要重启 `gateway`。

如果容器启动后才第一次创建某个覆盖文件，需要先重新生成 override 并重启对应服务一次：

```bash
./restart-service.sh gateway
```

之后继续修改该文件时，再按上面的热加载规则生效。
