# OrderSvr A/B 集群实现与故障处置手册

日期：2026-09-09
适用环境：DC SaaS Crypto，`ORDER_CLUSTER_ENABLED=true`

## 1. 当前状态

- 当前服务器：`18.140.45.126`，两个 OrderSvr JVM 运行在同一台主机。
- OrderSvrA：容器 `dc-saas-ordersvr`，GW 端口 `33036`，复制端口 `19121`。
- OrderSvrB：容器 `dc-saas-ordersvr-b`，GW 端口 `33041`，复制端口 `19122`。
- ZooKeeper：`dc-saas-zookeeper`，分区根路径 `/dc/cluster/ordersvr/partitions`。
- 逻辑服务名仍为 `OrderSvr`；GW 根据 `location + marketIndicator + securityID` 计算分区并路由到物理 A/B。
- 共 256 个分区 `P000..P255`。当前 A、B 各承担 128 个 Primary，另一节点作为 Replica。
- 当前一致性模式为 `SYNC_BATCHED`：每批最多 64 条，最长聚合等待 1000 微秒，2 个批处理线程。
- journal、state、commit、snapshot、promotion barrier、replication 和 readiness 均为 required。
- 2026-09-09 最终验收状态：epoch 48，256/256 READY，A/B 512 份快照的 256 对语义完全一致。

当前仍是同机双节点。它能隔离单 JVM 故障，但不能抵御整机、宿主文件系统或同机 ZooKeeper 故障。正式高可用需要把副本拆到独立故障域。

## 2. 请求和状态流

### 2.1 路由与 fencing

1. GW 从请求提取 `location + marketIndicator + securityID`。
2. `PartitionHasher` 将组合键稳定映射到 `P000..P255`。
3. GW 读取 ZooKeeper assignment：`partitionId / epoch / primary / replica / state`。
4. 只有 `state=READY` 才允许路由；否则返回 `PARTITION_NOT_READY`。
5. OrderSvr 再校验本节点确实是当前 epoch 的 Primary。旧 Primary 或旧 epoch 请求会被拒绝，防止双主写入。

### 2.2 写入与复制

一笔业务变更的恢复链路为：

```text
GW -> 当前 Primary
   -> command journal
   -> legacy matching/business mutation
   -> STATE_* post-state journal
   -> Primary -> Replica TCP SYNC_BATCHED replication
   -> Replica ACK
   -> STATE_COMMIT marker
   -> commit watermark
   -> ProjectionSvr 只投影已提交 state
```

`SYNC_BATCHED` 只合并 ACK，不跨 partition 或 epoch 合批。Replica 返回 sequence gap 时，Primary 从本地 journal 以最多 256 条一批补齐。ACK 的 partition、epoch、sequence 任一不匹配都会失败。

### 2.3 快照和恢复

- 每个分区有独立 journal、snapshot 和读写屏障。
- 普通订单变更持共享屏障；快照、恢复和 promotion 持独占屏障。
- 快照记录 `snapshotId`、epoch、snapshot sequence、committed state sequence 和 commit marker sequence。
- 恢复只重放 commit watermark 以内的完整状态前缀；未提交 tail 会被归档，不会被提升为业务状态。
- 跨 epoch 不能直接增量追赶。新 Primary 必须完成 commit-aware recovery，并把新 epoch snapshot 安装到 Replica。
- Replica 完成 `SNAPSHOT_BEGIN ... SNAPSHOT_END` 后，Primary 才输出 `ORDER_PARTITION_PROMOTION_READY` 并开放 readiness。
- 旧 epoch journal 移到 `.archive`，不直接删除，便于故障审计。

## 3. 一致性和可用性边界

当前选择是双副本 RPO=0 优先：

- Replica 不可用、ACK 超时、epoch 不一致或 promotion barrier 未完成时，相关分区拒绝写入。
- 不允许把 Replica 临时设为空，也不允许绕过 readiness 继续接单。
- 两节点架构不能同时提供“丢一个节点仍持续写入”和“每笔订单 RPO=0”。需要持续可写时，应增加第三副本和多数派协议，不能靠运维手工降级模拟。
- 当前 assignment/recovery 控制面由部署和恢复脚本推进，不是完整的自动故障转移控制器。

## 4. 日常健康检查

在服务器执行：

```bash
sudo bash -lc '
set -euo pipefail
source /home/ec2-user/dc-saas-deploy/.env.prod
WEB_LISTEN_PORT="$WEB_LISTEN_PORT" \
ORDER_CLUSTER_DATA_ROOT=/data/dc-saas-runtime/data \
  bash /home/ec2-user/dc-saas-order-cluster-dev-deploy/tests/verify-order-cluster-state-host.sh
'
```

成功标准必须全部满足：

```text
partitions=256 ready=256 epoch=<同一个值>
primaries={OrderSvrA:128, OrderSvrB:128}
replicas={OrderSvrA:128, OrderSvrB:128}
snapshots=512 semantic_pairs_equal=256 uppercase_SN=0
PASS: assignments, snapshots, route and container state are consistent
```

补充检查：

```bash
sudo docker inspect dc-saas-ordersvr dc-saas-ordersvr-b dc-saas-gateway \
  --format '{{.Name}} running={{.State.Running}} oom={{.State.OOMKilled}} restarts={{.RestartCount}} image={{.Config.Image}}'

sudo docker stats --no-stream \
  dc-saas-ordersvr dc-saas-ordersvr-b dc-saas-gateway dc-saas-zookeeper

sudo docker logs --since 10m dc-saas-ordersvr 2>&1 | \
  grep -E 'PARTITION_NOT_READY|STALE_PARTITION|REPLICATION|RECOVERY_FAILED|PROMOTION_BLOCKED|ERROR'

sudo docker logs --since 10m dc-saas-ordersvr-b 2>&1 | \
  grep -E 'PARTITION_NOT_READY|STALE_PARTITION|REPLICATION|RECOVERY_FAILED|PROMOTION_BLOCKED|ERROR'
```

不能只看容器 `Up` 或端口监听。必须同时验证 assignment、epoch、A/B snapshot、逻辑 `OrderSvr` 路由和业务响应。

## 5. 单节点故障恢复

症状通常包括：

- `replication request failed`
- `PARTITION_NOT_READY`
- `ORDER_PARTITION_PROMOTION_BLOCKED`
- 某个 OrderSvr 容器退出、OOM 或复制端口不监听

处置原则：保持 fail-closed，不手工降级成单副本。

```bash
sudo bash -lc '
set -euo pipefail
source /home/ec2-user/dc-saas-deploy/.env.prod

# 1. 先停止入口，防止恢复期间继续接单。
docker stop dc-saas-gateway

# 2. 只启动或重启故障节点。下面示例为 A；B 故障时替换容器名。
docker restart dc-saas-ordersvr

# 3. 确认 A/B 的业务端口和复制端口均已监听，再推进新 epoch 恢复。
wait_port() {
  local port="$1"
  for _ in $(seq 1 90); do
    ss -lnt | awk 'NR>1{print $4}' | grep -Eq "[:.]${port}$" && return 0
    sleep 2
  done
  return 1
}
for port in "$ORDERSVR_GW_PORT" "$ORDERSVR_B_GW_PORT" \
            "$ORDERSVR_A_REPLICATION_PORT" "$ORDERSVR_B_REPLICATION_PORT"; do
  wait_port "$port"
done

ORDER_CLUSTER_ZK_SERVER="127.0.0.1:${ZOOKEEPER_PORT}" \
  bash /home/ec2-user/dc-saas-order-cluster-dev-deploy/tests/recover-order-cluster-partitions-host.sh

# 4. 先验证 256 分区和 A/B 快照，再恢复 GW。
WEB_LISTEN_PORT="$WEB_LISTEN_PORT" \
ORDER_CLUSTER_DATA_ROOT=/data/dc-saas-runtime/data \
  bash /home/ec2-user/dc-saas-order-cluster-dev-deploy/tests/verify-order-cluster-state-host.sh

docker start dc-saas-gateway
'
```

GW 启动后继续轮询逻辑路由。后端重新连接存在短暂传播时间，出现一次 `SERVER.OrderSvr is not Online` 不能立即判定恢复失败，但不能在路由尚未恢复时开放流量。

## 6. 计划内重启或版本发布

1. 先确认无进行中的 E2E、压测、批量撤单或 Robot 配置切换。
2. 停 GW，避免新订单进入恢复窗口。
3. 同时更新 OrderSvrA/B，两个节点必须使用同一个不可变镜像。
4. 等待 A/B 业务和复制端口。
5. 执行 `recover-order-cluster-partitions-host.sh`，让 epoch 单调增加。
6. 执行 `verify-order-cluster-state-host.sh`。
7. 启动/刷新 GW，验证逻辑路由、登录、下单、撤单、成交、Projection、Trade、MD、Liq、Robot 和 Web。

正式发布顺序：

1. 先把集群 Common 技术包发布到中央仓库，并确认中央仓库已可解析。
2. OrderSvr 和 GW 同时升级到同一个 Common 正式版本。
3. 两个镜像内必须只有一个 Common JAR，且 SHA-256 完全一致。
4. 再构建 OrderSvr/GW 正式不可变镜像并部署 A/B/GW。
5. 禁止只升级 OrderSvr 或只升级 GW，避免 partition hash、assignment/readiness 协议不一致。

## 7. 数据异常和恢复禁区

出现 snapshot mismatch、journal gap、epoch mismatch 或 `RECOVERY_FAILED` 时：

1. 立即停 GW，保留 fail-closed。
2. 不删除任何 journal、snapshot、`.archive` 或 ZooKeeper assignment。
3. 备份以下目录：

```text
/data/dc-saas-runtime/data/OrderSvrA/journal
/data/dc-saas-runtime/data/OrderSvrA/snapshot
/data/dc-saas-runtime/data/OrderSvrB/journal
/data/dc-saas-runtime/data/OrderSvrB/snapshot
/data/dc-saas-runtime/data/zookeeper
```

4. 保存 A/B 从故障前 10 分钟到当前的 Docker 日志、当前 assignment JSON 和镜像 ID。
5. 根据 commit watermark 选定权威 committed prefix，再决定 snapshot rebase；不能凭“文件更新时间更新”选择主副本。

禁止动作：

- 禁止 `rm -rf` journal/snapshot 后直接启动生产流量。
- 禁止把 epoch 改小或重置为 1。
- 禁止把 `RECOVERING` 直接手改为 `READY`。
- 禁止在未确认 commit watermark 时复制单侧 journal 覆盖另一侧。
- 禁止在 A/B snapshot 不一致时启动 GW。
- 禁止用直接删除 MySQL 订单代替 OrderSvr API 撤单；OrderSvr journal 仍可能恢复该活动单。

## 8. 常见症状定位

| 症状 | 优先检查 | 处理 |
|---|---|---|
| 所有订单返回 `PARTITION_NOT_READY` | ZooKeeper 256 assignments、A/B promotion 日志 | 停 GW，修复缺失节点，执行 staged epoch recovery |
| 只有部分租户/币种失败 | 用 `location + market + security` 定位 partition | 检查该 partition 的 epoch、Primary、Replica、snapshot 和日志 |
| `STALE_PARTITION` 或旧 Primary 拒绝 | GW/Order 当前 assignment epoch 是否一致 | 不重试写旧节点；等待路由刷新或推进新 epoch recovery |
| `replication request failed` | Replica 容器、19121/19122、ACK timeout | 恢复 Replica，不允许单副本降级 |
| `replica catch-up crosses epoch` | 旧 epoch 存在 gap | 使用跨 epoch snapshot rebase，不直接增量补 journal |
| A/B snapshot mismatch | 两侧 snapshotId/epoch/committed state seq | 停流量并备份，选择权威 committed prefix 后恢复 |
| 容器运行但 GW 报服务离线 | GW 重启后的后端注册传播 | 轮询逻辑路由；超时后再重启对应后端，不以端口代替路由验证 |
| Order 查询有单但 MySQL `leaves_qty` 为空 | Projection 事件字段和 watermark | 当前字段是 `unOpenQty`，兼容旧 `unCumQty`；不要先归因于 Order 恢复 |
| `bliplink` 盘口不变化 | `WEB_E2E/continuous-depth10` 的 enabled/runtime/open_order_count | RobotSvr 进程正常不代表配置启用；应为 `enabled=1/RUNNING/40` |

## 9. 当前证据

- 全系统最终状态：`/data/dc-saas-runtime/e2e-artifacts/final-restore-FINAL_0909024802`
- 角色反转：`/data/dc-saas-runtime/e2e-artifacts/role-reversal-ROLE_ROUTE_0908224752`
- 同步副本故障拒单：`/data/dc-saas-runtime/e2e-artifacts/sync-failure-SYNC_FAIL_0908231226`
- 1000 单压力、重启和账务：`/data/dc-saas-runtime/e2e-artifacts/stress-ORDCLUSTER_0908213348`
- Liq E2E：`/data/dc-saas-runtime/e2e-artifacts/liq-LIQ_CC8546A_R2_0909022458`
- Robot E2E：`/data/dc-saas-runtime/e2e-artifacts/robot-C0909_0909023549`
- `bliplink` 连续盘口恢复：`/data/dc-saas-runtime/e2e-artifacts/robot-web-e2e-restore-0909032807`
