# 逐服务切换

本文说明生产上按服务逐个切到容器的方式。

## 当前第一批目标

第一批支持 `batchsvr` 和 `simsvr`。

- 旧服务：`BatchSvr`
- 容器：`dc-batchsvr`
- 端口：`30046`
- 镜像：`ghcr.io/bliplink/batchsvr:${BATCHSVR_TAG}`
- 旧服务：`SIMSvr`
- 容器：`dc-simsvr`
- 端口：`30045`
- 镜像：`ghcr.io/skt-walter/simsvr:${SIMSVR_TAG}`

## 生产默认值

第一次 BatchSvr 切换使用 `.env.prod.batchsvr.example` 作为模板。

关键默认值：

- `DEPLOY_ROOT=/data/strategy`
- `RUNTIME_UID=1000`
- `RUNTIME_GID=1000`
- `SERVICE_HOST=14.0.47.20`
- `CLICKHOUSE_MODE=external`
- `CLICKHOUSE_HOST=14.0.47.20`
- `CLICKHOUSE_USERNAME=default`
- `CLICKHOUSE_PASSWORD=change-me-in-local-env-prod`

真实生产密码只放在生产机本地 `.env.prod`，不要提交到 Git。

## Dry Run

正式动服务前先执行：

```bash
./deploy-service.sh batchsvr --dry-run
./rollback-service.sh batchsvr --dry-run
./deploy-service.sh simsvr --dry-run
./rollback-service.sh simsvr --dry-run
```

dry run 输出中只能出现 `batchsvr` 目标，不能调用全量 `deploy.sh`。

`SERVICE_HOST` 是切换脚本检查服务端口打开/关闭时使用的主机地址。生产上要使用真实绑定地址，不要固定写死 `127.0.0.1`，因为现有 DC 服务可能直接绑定服务器 IP。

## Docker 前置安装

如果 Ubuntu 22.04 生产机还没有 Docker，先安装 Docker Engine 和 Compose plugin。这个步骤只准备 Docker，不启动任何 DC 业务容器。

```bash
apt-get update
apt-get install -y ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
usermod -aG docker dc
docker --version
docker compose version
systemctl is-active docker
```

把 `dc` 加入 `docker` 组之后，需要重新登录一次 SSH，让组权限生效。如果当前自动化会话仍然不能用 `dc` 访问 Docker，就先 `newgrp docker` 或重新连接后再执行切换脚本。

## 服务切换流程

1. 将 `.env.prod.batchsvr.example` 复制为 `.env.prod`，必要时调整 tag。
2. 确认 Docker 与 Compose 可用。
3. 确认 GHCR 登录可用。
4. 执行 `./deploy-service.sh <service> --dry-run`。
5. 执行 `./deploy-service.sh <service>`。
6. 确认目标容器正在运行。
7. 确认目标端口可达。
8. 检查 `docker logs <container> --tail 200`。
9. 检查 `/data/strategy/log/` 下对应服务日志。
10. 确认其它旧服务 PID 没有变化。

## 回滚

只回滚 BatchSvr：

```bash
./rollback-service.sh batchsvr
```

回滚脚本只会停止 `batchsvr` 容器，并只恢复旧 `BatchSvr`。

## 单服务运行挂载

Java 服务容器使用 `1000:1000` 运行，避免容器写出的日志/数据破坏旧脚本回滚。但当前部分服务镜像里的应用目录是 root-owned，所以 Compose 会直接挂载这些路径，避免入口脚本在镜像目录里创建软链：

- `${DEPLOY_ROOT}/data -> /srv/dc/dc/BatchSvr/data`
- `${DEPLOY_ROOT}/log -> /srv/dc/dc/BatchSvr/log`
- `${DEPLOY_ROOT}/data -> /srv/dc/dc/SIMSvr/data`
- `${DEPLOY_ROOT}/log -> /srv/dc/dc/SIMSvr/log`

一旦某个服务单独声明 `volumes`，也要显式保留公共挂载：

- `${DEPLOY_ROOT}/control -> /srv/dc/control:ro`
- `${DEPLOY_ROOT}/data -> /srv/dc/data`
- `${DEPLOY_ROOT}/log -> /srv/dc/log`

原因是 Compose 不会合并 YAML anchor 里的列表；服务级 `volumes` 会替换基础模板里的 `volumes`。

## ClickHouse 校验

本轮生产单服务切换只支持外置 ClickHouse。`deploy-service.sh batchsvr` 会校验：

- `CLICKHOUSE_MODE=external`
- `CLICKHOUSE_HOST:CLICKHOUSE_HTTP_PORT` 可连通
- `dc.signal` 表存在
- 至少存在一张 `dc.strategy_system_daily_report*` 表

单服务切换脚本不会初始化或修改生产 ClickHouse。

对于 `simsvr`，`deploy-service.sh simsvr` 会校验 `strategy_backtest_task` 和 `backtest_result` 两张表存在。

## 后续顺序

BatchSvr 稳定后，建议顺序：

1. `simsvr`
2. `indsvr`
3. `apssvr`
4. `mdsvr`
5. `quantsvr`
6. `gateway`
7. `web`
8. `zookeeper`

不要提前切 `zookeeper`。它是注册中心，应在应用服务验证稳定之后再切。

## 单服务重启

服务已经切到容器后，日常重启不再走旧的 `scripts/start` / `scripts/stop`，统一使用：

```bash
./restart-service.sh apssvr --dry-run
./restart-service.sh apssvr
```

该脚本只重建目标容器：

- 不拉取新镜像
- 不启动依赖服务
- 使用 `docker compose up -d --no-deps --force-recreate <service>`
- 每次执行前都会重新生成 `compose.override.generated.yaml`

生产 APSSvr 参考旧系统 `restartjob.sh`，每天 `00:05` 定时重启：

```cron
5 0 * * * cd /data/strategy/dc-quant-deploy && ./restart-service.sh apssvr >> /data/strategy/log/cron-apssvr-restart.log 2>&1
```
