# 系统维护手册

本文说明 DC Quant 部署后的常用维护动作。

## 1. 查看状态

```bash
cd /opt/source/dc-quant-deploy
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml ps
```

如果使用内置 ClickHouse，需要查看包含 ClickHouse profile 的状态：

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml --profile embedded-clickhouse ps
```

## 2. 启停服务

重启单个服务：

```bash
./restart-service.sh apssvr
```

停止单个服务：

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml stop apssvr
```

启动单个服务：

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml up -d --no-deps apssvr
```

常用服务名：

- `zookeeper`
- `gateway`
- `mdsvr`
- `apssvr`
- `quantsvr`
- `indsvr`
- `simsvr`
- `batchsvr`
- `web`
- `clickhouse`

## 3. 查看日志

查看容器日志：

```bash
docker logs dc-apssvr --tail 200
docker logs dc-gateway --tail 200
```

查看宿主机日志：

```bash
tail -n 100 ${DEPLOY_ROOT}/log/APSSvr.log
tail -n 100 ${DEPLOY_ROOT}/log/QuantSvr.log
```

扫描最近错误：

```bash
for c in dc-gateway dc-mdsvr dc-apssvr dc-quantsvr dc-indsvr dc-simsvr dc-batchsvr dc-web dc-zookeeper; do
  echo "===== $c ====="
  docker logs "$c" --since 5m 2>&1 | grep -Ei 'ERROR|Exception|timeout|permission denied|address already in use' || true
done
```

## 4. 健康检查

Web：

```bash
curl -I http://127.0.0.1/web/
```

ZooKeeper：

```bash
printf ruok | nc -w 3 127.0.0.1 2181
```

ClickHouse：

```bash
curl 'http://127.0.0.1:8123/?query=SELECT%201'
```

端口：

```bash
ss -lntp | grep -E '(:80|:2181|:3000|:3001|:3002|:30028|:30035|:30042|:30044|:30045|:30046|:8123|:9000)\b'
```

## 5. 修改日志级别

默认使用镜像内置配置。需要覆盖时，把文件放到：

```text
${DEPLOY_ROOT}/control/overrides/<Service>/config/log4j.ini
```

例如：

```text
${DEPLOY_ROOT}/control/overrides/APSSvr/config/log4j.ini
```

新增覆盖文件后重启服务一次：

```bash
./restart-service.sh apssvr
```

已有挂载的 `log4j.ini` 修改后通常可以热生效。

## 6. 升级镜像

修改 `.env.prod` 中对应 tag：

```dotenv
APSSVR_TAG=v0.0.2
```

拉取并重启：

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml pull apssvr
./restart-service.sh apssvr
```

升级后检查：

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml ps
docker logs dc-apssvr --tail 200
```

## 7. 备份

建议至少备份：

- `.env.prod`
- `control.prod/`
- `${DEPLOY_ROOT}/control`
- `${DEPLOY_ROOT}/data`
- `${DEPLOY_ROOT}/log`

示例：

```bash
TS=$(date +%Y%m%d-%H%M%S)
BACKUP=/opt/dc-backup/$TS
mkdir -p "$BACKUP"
cp -a .env.prod "$BACKUP/env.prod"
cp -a control.prod "$BACKUP/control.prod"
cp -a ${DEPLOY_ROOT}/control "$BACKUP/control"
cp -a ${DEPLOY_ROOT}/data "$BACKUP/data"
cp -a ${DEPLOY_ROOT}/log "$BACKUP/log"
```

如果使用外置 ClickHouse，数据库备份按现有 ClickHouse 方案处理。

## 8. 回滚

推荐用镜像 tag 回滚：

```bash
vi .env.prod
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml pull apssvr
./restart-service.sh apssvr
```

如果是全量部署失败：

```bash
./rollback.sh
```

回滚不会删除 ClickHouse 数据。

## 9. 定时重启

如果确实需要定时重启某个服务，可以使用 `restart-service.sh`：

```cron
5 0 * * * cd /opt/source/dc-quant-deploy && ./restart-service.sh apssvr >> /opt/dc-runtime/log/cron-apssvr-restart.log 2>&1
```

安装前先备份 crontab：

```bash
crontab -l > ~/crontab.backup.$(date +%Y%m%d%H%M%S).txt
crontab -e
```
