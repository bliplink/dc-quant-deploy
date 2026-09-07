# OrderSvr A/B 与 GW 本机联测报告

日期：2026-09-07

## 结论

本机已完成 `GW + OrderSvrA + OrderSvrB + ZooKeeper` 独立进程联测。逻辑服务名保持为 `OrderSvr`，GW 按 `location + marketIndicator + securityID` 计算分区并路由到物理节点；主节点写入 Chronicle Queue 后，通过独立 TCP 复制端口同步复制到另一节点并取得 `ACK=OK`。

本轮验证不切换现有环境流量，不连接生产 MySQL/ClickHouse，所有端口、配置、日志和数据均位于 `.cluster-dev/order-ab-local/<run-id>` 隔离目录。测试结束后脚本自动清理本轮 Java 进程。

## 注册与路由模型

- Web、Robot 和其他服务继续调用逻辑服务 `OrderSvr`。
- 物理节点使用独立 `serverKey` 和注册服务名：`OrderSvrA`、`OrderSvrB`。
- A/B 的 `RegType=0`，即全活注册模式；不使用旧的主备注册方式。
- GW 的 `LBConfig.OrderSvr=Partition`，分区表中的 `primary` 决定实际节点。
- 两个节点的复制协议使用同一个逻辑命名空间 `SERVER.OrderSvr`；该值与节点自身 `serverKey` 分离，防止对端误判为不同服务并拒绝复制。
- 当前联测分区：P027 主 A 备 B；P132 主 B 备 A。

## 版本与产物

- Common：`811eeeca05b3`
- OrderSvr：`8ac36adf7afb`
- Gateway library：`6702148f925c`
- GW wrapper：`d8ab7047129c`
- Deploy 联测脚本：`adfaa6bd02ca`
- Common JAR SHA-256：`58252184ca8e58e6655ffa00588425f96e9c3a2d7dc263a76b54d254c24e15cd`
- OrderSvr 开发镜像标识：`dc-saas/ordersvr:cluster-dev-8ac36adf7afb-common-811eeeca05b3`
- GW 开发镜像标识：`dc-saas/gw:cluster-dev-d8ab7047129c-gateway-6702148f925c-common-811eeeca05b3`

本机没有 Docker CLI，因此本轮只生成并校验 Maven 运行产物与镜像构建清单，没有在本机生成 Docker 镜像。

## 自动化测试结果

- Common：17 项，失败 0，错误 0。
- OrderSvr：111 项，失败 0，错误 0，跳过 0。
- Common -> com.app.dc -> OrderSvr -> Gateway -> GW wrapper 完整构建：通过。
- A/B/GW 最终联测运行：`20260907-115854`，结果 `PASS`。

关键路由与复制证据：

```text
WEB_E2E/4/BTCUSDT -> P027 -> OrderSvrA -> OrderSvrB
ORDER_CLUSTER_COMMAND_RECORDED node:OrderSvrA, partition:P027, epoch:1, seq:1, replicaStatus:OK

WEB_E2E/4/ETHUSDT -> P132 -> OrderSvrB -> OrderSvrA
ORDER_CLUSTER_COMMAND_RECORDED node:OrderSvrB, partition:P132, epoch:1, seq:1, replicaStatus:OK
```

本机执行命令：

```powershell
.\build-cluster-dev-ordersvr.ps1 -IncludeGateway -SkipDockerBuild
.\tests\run-order-cluster-ab-local.ps1 -SkipBuild
```

## 尚未完成的集群验收

以下项目不能因本次联测通过而宣称完成：

1. ZooKeeper 角色变更到 OrderSvr 自动恢复/自动提升的生产生命周期尚未接通。
2. 主节点停止、备节点补齐日志、提升、原主恢复后的 fencing 和回切尚未做进程级故障演练。
3. 当前 Common/Gateway 集群依赖尚未正式发布 Maven Central，开发产物不得替换生产正式依赖。
4. Docker 双实例覆盖、服务器资源限制、持久化目录、健康检查和一键回滚仍需在隔离服务器环境验证。
5. 带真实 MySQL 资金、撮合、成交、TradeSvr 回报以及 Web/Robot 流量的完整业务回归，需要在服务器隔离栈完成。

## 下一步发布边界

服务器测试只允许使用独立 Compose project、独立容器名、独立端口和独立数据目录，且不得接管现有生产 `OrderSvr`。确认 Docker 故障演练、业务回归和回滚均通过后，再发布 Common/Gateway 正式版本和公开 GHCR 镜像，最后安排生产流量切换。
