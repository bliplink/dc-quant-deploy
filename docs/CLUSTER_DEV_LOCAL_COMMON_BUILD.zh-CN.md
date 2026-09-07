# 集群开发期本地 Common Docker 验证

## 目的

在不发布 Maven Central 的情况下，将本地编译的 `com.app.common` 固化进 OrderSvr、GW 开发镜像，用于集群功能联调。该流程只用于开发和验收；正式生产镜像仍必须先发布 Maven Central，再由 GitHub Actions 构建公开 GHCR 镜像。

## 当前依赖链

```text
io.github.bliplink:com.app.common:3.0.5
├─ com.app.dc:com.app.dc:0.0.3-SNAPSHOT
│  └─ com.app.dc:com.app.dc.ordersvr:0.0.1-SNAPSHOT
└─ io.github.bliplink:gw:3.0.6
   └─ io.github.bliplink:gw-app:3.0.3
```

OrderSvr 不是直接引用 `com.app.common`，而是通过 `com.app.dc` 传递引用。GW library 直接引用 `com.app.common`，GW运行镜像由 `gw-app` wrapper 构建。因此不能只向容器复制一个 Common JAR，必须按依赖链重新编译。

## 安全约束

- 使用部署仓库下的 `.cluster-dev/m2` 隔离 Maven 仓库，不修改用户默认 `~/.m2`。
- 构建前校验实际 Maven GAV；版本不一致立即失败。
- 每个运行产物只能包含一个 `com.app.common` JAR。
- 同一轮 OrderSvr 和 GW 构建必须包含相同 SHA256 的 Common JAR。
- 镜像标签包含服务和 Common commit，镜像 Label 保存完整来源信息。
- 不覆盖 `saas-crypto`、`latest` 或正式版本标签。
- 不使用 volume 覆盖容器运行时 JAR。
- 本地开发镜像不得加入生产自动更新任务。

## Windows构建

只构建并检查 Maven 产物：

```powershell
.\build-cluster-dev-ordersvr.ps1 -SkipDockerBuild
```

同时构建 OrderSvr 和 GW：

```powershell
.\build-cluster-dev-ordersvr.ps1 -IncludeGateway
```

如果工作区中已有与当前源码不兼容的测试源码，可先完成临时开发镜像构建：

```powershell
.\build-cluster-dev-ordersvr.ps1 -IncludeGateway -SkipTests
```

`-SkipTests` 会跳过测试源码编译，不能作为正式验收结果。严格测试必须在正确且干净的集群分支上重新执行。

## Linux/Docker主机构建

源码默认位于部署仓库父目录；也可以通过环境变量传入绝对路径：

```bash
COMMON_LIBRARY_SOURCE=/data/build/com.app.common \
DC_COMMON_SOURCE=/data/build/com.app.dc \
ORDERSVR_SOURCE=/data/build/ordersvr \
GATEWAY_LIBRARY_SOURCE=/data/build/gateway/gateway \
GATEWAY_IMAGE_SOURCE=/data/build/gw-image \
INCLUDE_GATEWAY=true \
./build-cluster-dev-ordersvr.sh
```

脚本使用 Maven Docker 镜像编译，不要求宿主机安装 Maven。

## 构建输出

默认镜像标签示例：

```text
dc-saas/ordersvr:cluster-dev-<ordersvr-sha>-common-<common-sha>
dc-saas/gw:cluster-dev-<wrapper-sha>-gateway-<gateway-sha>-common-<common-sha>
```

构建清单保存在：

```text
.cluster-dev/ordersvr-build-manifest.json
.cluster-dev/gw-build-manifest.json
```

Linux脚本输出对应的 `.env` 清单。`.cluster-dev/` 已加入 `.gitignore`，不得提交 Maven 缓存或本地构建产物。

## 镜像核验

```bash
docker image inspect "$ORDERSVR_IMAGE" --format '{{json .Config.Labels}}'
docker run --rm --entrypoint sh "$ORDERSVR_IMAGE" -c \
  'find /srv/dc/dc/OrderSvr/lib -maxdepth 1 -name "com.app.common-*.jar" -print -exec sha256sum {} \;'
```

必须确认：

1. 只输出一个 Common JAR；
2. JAR SHA256 与构建清单一致；
3. `dc.common.revision` 与计划验证的 Common commit 一致；
4. OrderSvr 与 GW 的 `dc.common.jar.sha256` 完全相同。

## 双OrderSvr部署前置门槛

双实例 Compose 覆盖只有在分区集群分支同步后才能启用。必须先确认该分支定义的节点标识、监听端口、ZooKeeper路径、分区键和主备/分片语义，禁止根据旧版 `serverKey=SERVER.OrderSvr` 猜测配置，否则同机两个实例可能端口冲突或形成双主。

确认配置契约后再完成：

- `compose.cluster-dev.yaml`；
- OrderSvr-A/B独立配置、日志和状态目录；
- 禁用单实例OrderSvr和自动更新；
- 主节点停止、备用接管、原主恢复和ZooKeeper会话过期测试。

## 正式发布顺序

```text
发布 com.app.common 到 Maven Central
→ 确认 Central 可下载且校验值正确
→ 更新并发布 com.app.dc / gateway library
→ 更新 OrderSvr / GW wrapper 依赖
→ GitHub Actions 构建公开 GHCR 镜像
→ 使用 sha 标签或 digest 发布生产
```

正式发布不得直接复用本地 Maven 缓存或本地镜像。
