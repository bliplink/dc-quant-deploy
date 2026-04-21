# 逐服务切换

本文说明生产上按服务逐个切到容器的方式。

## 当前第一批目标

第一批只支持 `batchsvr`。

- 旧服务：`BatchSvr`
- 容器：`dc-batchsvr`
- 端口：`30046`
- 镜像：`ghcr.io/bliplink/batchsvr:${BATCHSVR_TAG}`

## 生产默认值

第一次 BatchSvr 切换使用 `.env.prod.batchsvr.example` 作为模板。

关键默认值：

- `DEPLOY_ROOT=/data/strategy`
- `RUNTIME_UID=1000`
- `RUNTIME_GID=1000`
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
```

dry run 输出中只能出现 `batchsvr` 目标，不能调用全量 `deploy.sh`。

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

## BatchSvr 切换流程

1. 将 `.env.prod.batchsvr.example` 复制为 `.env.prod`，必要时调整 tag。
2. 确认 Docker 与 Compose 可用。
3. 确认 GHCR 登录可用。
4. 执行 `./deploy-service.sh batchsvr --dry-run`。
5. 执行 `./deploy-service.sh batchsvr`。
6. 确认 `dc-batchsvr` 正在运行。
7. 确认端口 `30046` 可达。
8. 检查 `docker logs dc-batchsvr --tail 200`。
9. 检查 `/data/strategy/log/BatchSvr.log`。
10. 确认其它旧服务 PID 没有变化。

## 回滚

只回滚 BatchSvr：

```bash
./rollback-service.sh batchsvr
```

回滚脚本只会停止 `batchsvr` 容器，并只恢复旧 `BatchSvr`。

## ClickHouse 校验

本轮生产单服务切换只支持外置 ClickHouse。`deploy-service.sh batchsvr` 会校验：

- `CLICKHOUSE_MODE=external`
- `CLICKHOUSE_HOST:CLICKHOUSE_HTTP_PORT` 可连通
- `dc.signal` 表存在
- 至少存在一张 `dc.strategy_system_daily_report*` 表

单服务切换脚本不会初始化或修改生产 ClickHouse。

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
