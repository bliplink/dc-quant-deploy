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

## 服务器隔离集群验收（18.140.45.126）

服务器已使用独立 Compose project `dc-saas-order-cluster-dev`、独立 ZooKeeper `127.0.0.1:32182`、独立端口和 `/data/dc-saas-order-cluster-dev` 数据目录完成部署。现有量化和 SaaS 的 GW、OrderSvr 容器未替换、未重启、未接流量。

本轮服务器版本：

- Common：`811eeeca05b33e77017081cf08178a3993c88919`
- OrderSvr：`ff25f5bba2f6a3fce151ae7572f66c3d41a8237e`
- Deploy：`289793a`
- OrderSvr 镜像：`ghcr.io/bliplink/ordersvr:cluster-dev-ff25f5b`
- GW 镜像：`ghcr.io/bliplink/ordersvr:gw-cluster-dev-ff25f5b`
- OrderSvr 镜像摘要：`sha256:6b8af27ca96f22cf1a13125255d8838cb23a5dd8d5b436bd809caa1aa9d29382`
- GW 镜像摘要：`sha256:c0fddd26ce468f914a996c7ca6122efe456f96497050b7a8627c782047114fdf`
- 两个镜像内嵌 Common JAR SHA-256：`816f3d672421e0bc21cb17f1be1feec1e678fded53af0c1ce5ef12edc0d976fc`

验证结果：

1. OrderSvr 本地全量测试 112 项全部通过；GitHub Actions 的 Common、OrderSvr 测试/镜像和 GW 镜像任务全部通过。
2. 服务器 A/B 分区路由与同步复制通过：BTCUSDT 的 P027 为 A 主/B 备，ETHUSDT 的 P132 为 B 主/A 备，两个方向均为 `replicaStatus:OK`。
3. P027 在线角色反转通过：epoch 单调递增，先 A→B，再 B→A，两个方向均通过 GW 逻辑服务路由并取得同步副本 ACK；最终恢复 A 主/B 备。
4. 隔离 GW 未连接现有 SaaS OrderSvr 的 33036 端口；租户交易规则数据库刷新在两台隔离 OrderSvr 上均关闭，本轮增量日志无相应刷新异常。
5. A/B/GW 测试可重复运行；测试不再依赖仅在首次启动时出现的连接日志。
6. 重装不会覆盖已有 ZooKeeper assignment。P027 在连续重装、上一版切换和回滚后仍保持 epoch `178878980152156`，未回退到初始值 1。
7. 不可变镜像一键回滚通过：先从 `ff25f5b` 切换到 `59774b6`，再由 `rollback-order-cluster-dev.sh` 恢复 `ff25f5b`；最终 A/B 路由与同步复制复测通过。

机器可读证据：

```text
/data/dc-saas-order-cluster-dev/evidence/20260907-143511/result.json
/data/dc-saas-order-cluster-dev/evidence/20260907-140321-role-reversal/result.json
/data/dc-saas-order-cluster-dev/deploy-state/last-successful.env
/data/dc-saas-order-cluster-dev/deploy-state/rollback.env
```

上述两个结果的 `businessOrderAcceptance` 均为 `NOT_TESTED`。隔离栈故意不接 LoginSvr、AdminSvr、TradeSvr、资金和行情；测试请求用于验证分区命令进入正确物理节点并同步复制，不能据此宣称真实交易下单成功。

## 尚未完成的集群验收

以下项目不能因本次联测通过而宣称完成：

1. ZooKeeper 在线角色变更已经验证，但由故障检测器自动生成角色变更、OrderSvr 自动恢复/自动提升的生产生命周期尚未接通。
2. 当前 `state/commit/snapshot` 在隔离部署中仍关闭，因此尚未注入主节点宕机；备节点补齐业务状态、提升、原主恢复后的 fencing 和回切不能宣称完成。
3. 当前 Common/Gateway 集群依赖尚未正式发布 Maven Central，开发产物不得替换生产正式依赖。
4. Docker 双实例、服务器资源限制、持久化目录和一键回滚已完成隔离验证；容器健康检查与故障自动化仍需补齐。
5. 带真实 LoginSvr/MySQL 资金、撮合、成交、TradeSvr 回报以及 Web/Robot 流量的完整业务回归，需要在服务器隔离栈完成。

## 下一步发布边界

服务器测试只允许使用独立 Compose project、独立容器名、独立端口和独立数据目录，且不得接管现有生产 `OrderSvr`。确认 Docker 故障演练、业务回归和回滚均通过后，再发布 Common/Gateway 正式版本和公开 GHCR 镜像，最后安排生产流量切换。
