# 架构说明

## 范围

`dc-quant-deploy` 将 DC 运行时打包为单机 Docker Compose 部署。

服务范围：

- `zookeeper`
- `gateway` (`GW`)
- `mdsvr`
- `apssvr`
- `quantsvr`
- `indsvr`
- `simsvr`
- `batchsvr`
- `web`
- `clickhouse`

## 服务职责

- `GW = gateway`
- `quantsvr` 负责运行时交易与外部信号处理
- `indsvr` 负责生成与策略候选生命周期
- `simsvr` 负责回测与优化执行
- `batchsvr` 负责定时报表与汇总
- `clickhouse` 是唯一数据库
- `zookeeper` 是注册中心骨干

## 镜像映射

- `ghcr.io/bliplink/zookeeper:${ZOOKEEPER_TAG}`
- `ghcr.io/bliplink/gw:${GW_TAG}`
- `ghcr.io/bliplink/mdsvr:${MDSVR_TAG}`
- `ghcr.io/bliplink/apssvr:${APSSVR_TAG}`
- `ghcr.io/bliplink/quantsvr:${QUANTSVR_TAG}`
- `ghcr.io/bliplink/indsvr:${INDSVR_TAG}`
- `ghcr.io/SKT-Walter/simsvr:${SIMSVR_TAG}`
- `ghcr.io/bliplink/batchsvr:${BATCHSVR_TAG}`
- `ghcr.io/SKT-Walter/web:${WEB_TAG}`
- `clickhouse/clickhouse-server:${CLICKHOUSE_IMAGE_TAG}`

## 依赖关系

- `zookeeper` 提供注册中心端点
- `clickhouse` 提供持久化数据存储
- 所有 Java 服务同时依赖 `zookeeper` 和 `clickhouse`
- `web` 依赖 `gateway`

## ZooKeeper 事实来源

这个仓库只消费已发布的 ZooKeeper 镜像。

- 源码仓库：`https://github.com/bliplink/zookeeper`
- 发布镜像：`ghcr.io/bliplink/zookeeper`
- 已验证的独立运行镜像：`ghcr.io/bliplink/zookeeper:v0.0.2-test`

此前“只有薄包装”的说法已经不再适用于当前已发布镜像。现在的 ZooKeeper 仓库已经内置可运行源码树，并产出可独立运行的镜像。

## 运行时挂载契约

Java 服务保持现有内部目录约定：

- `${DEPLOY_ROOT}/control -> /srv/dc/control`
- `${DEPLOY_ROOT}/data -> /srv/dc/data`
- `${DEPLOY_ROOT}/log -> /srv/dc/log`
- `${DEPLOY_ROOT}/tpc/tpc -> /srv/dc/tpc/tpc`

ZooKeeper 继续读取宿主机侧运行时配置与数据：

- `${DEPLOY_ROOT}/tpc/zookeeper/conf/zoo.cfg`
- `${DEPLOY_ROOT}/tpc/zookeeper/conf/jaas.conf`
- `${DEPLOY_ROOT}/tpc/zookeeper/data`

ClickHouse 数据持久化目录：

- `${DEPLOY_ROOT}/clickhouse/data`
- `${DEPLOY_ROOT}/clickhouse/log`
