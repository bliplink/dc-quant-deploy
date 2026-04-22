# 架构说明

## 范围

`dc-quant-deploy` 将 DC 运行时打包为单机 Docker Compose 部署。

服务范围：

- `zookeeper`
- `GW`
- `mdsvr`
- `apssvr`
- `quantsvr`
- `indsvr`
- `simsvr`
- `batchsvr`
- `web`
- `clickhouse`

## 服务职责

- `GW` 是对外统一服务名；Docker Compose 内部服务键仍为 `gateway`，用于兼容现有脚本。
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
- `ghcr.io/skt-walter/simsvr:${SIMSVR_TAG}`
- `ghcr.io/bliplink/batchsvr:${BATCHSVR_TAG}`
- `ghcr.io/skt-walter/web:${WEB_TAG}`
- `clickhouse/clickhouse-server:${CLICKHOUSE_IMAGE_TAG}`

## 依赖关系

- `zookeeper` 提供注册中心端点
- `clickhouse` 提供持久化数据存储
- 所有 Java 服务同时依赖 `zookeeper` 和 `clickhouse`
- `web` 依赖 `GW`

## 运行时挂载契约

Java 服务保持现有内部目录约定：

- `${DEPLOY_ROOT}/control -> /srv/dc/control`
- `${DEPLOY_ROOT}/data -> /srv/dc/data`
- `${DEPLOY_ROOT}/log -> /srv/dc/log`

ZooKeeper 使用镜像内置配置，宿主机只持久化运行数据与日志：

- `${DEPLOY_ROOT}/data/zookeeper -> /opt/zookeeper/data`
- `${DEPLOY_ROOT}/log -> /opt/zookeeper/runtime/log`

ClickHouse 数据持久化目录：

- `${DEPLOY_ROOT}/data/clickhouse`
- `${DEPLOY_ROOT}/log/clickhouse`

初始化后的宿主机运行根目录只需要保留：

- `${DEPLOY_ROOT}/control`
- `${DEPLOY_ROOT}/data`
- `${DEPLOY_ROOT}/log`

运行时可选覆盖文件放在：

- `${DEPLOY_ROOT}/control/overrides/<Service>/config/<file>`

只有已经存在的覆盖文件才会挂载；不存在时继续使用镜像内置默认配置。
