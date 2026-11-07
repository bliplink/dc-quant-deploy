# OpenTradingCore｜Common / Order / Trade 部署防回归手册

> 长期维护文档。首次整理：2026-11-07（T534）。分支：`saas-crypto-latest`；主仓：`bliplink/dc-quant-deploy`。
> 目标：今后新增服务、单机与 A/B 集群部署、Common 升级，都在**启动前**检查历史反复出现的接线和数据问题，不再依靠上线后报错找原因。
> 本文只定义发布流程和检查。**通过本手册不代表真实交易、资金一致性或自动 HA 通过。**

## 一、不可突破的服务边界

- **Common 独占**：节点身份、ZooKeeper 租约和 Epoch、分区路由、WAL / Snapshot / 恢复、TCP 复制、真实物理 ACK、主切和撤权、归档、READY 门禁。
- **Order / Trade / Demo / 新业务**：只实现业务状态机、业务快照/原始命令的 `byte[]` 编解码、应用和回放；不得新增独立选主、Watch、Epoch、复制、ACK 或业务感知的 Common 持久化限制。
- **Gateway / Projection / MD 等消费者**：使用同一个已验收的 Common 客户端与分区路由；不得自行猜 Primary 或使用旧 `Common 3.0.15` 实现。
- 默认使用 `saas-crypto-latest`，所有服务引用**同一个、记录了 SHA256 的 Common JAR**。GitHub Actions 非本轮编译方式；优先本地构建、真实 Docker 验证、再更新镜像。
- 开发环境可全新部署并丢弃*已确认隔离的测试数据*，但绝不将不同 Epoch、旧 MySQL Projection、旧 Robot 和新原始 WAL 混合。严禁通过删除租约、伪造 RSA/ACK/Ledger、直接改 E2 状态来强行启动。

## 二、部署故障清单：现象 → 证据 → 根因 → 预防

| 编号 | 真实问题及误判风险 | 确认根因 | 永久预防措施 |
| --- | --- | --- | --- |
| D01 | Order/Trade E1 Birth 连不上 ZK，`UnresolvedAddressException` | T523 配置带入旧 `t84-…:2181`；T530 实际 ZK 是新 `42181` | 生成配置后核对 `REGISTER.Svr1.Host` 与所有 Common `*.control.zkHosts` 一致。执行 `preflight_saas_cluster_config.py --runtime-root`，不接受残留旧 ZK。 |
| D02 | `OrderSvrB` 绑定错误端口 80；Common Gateway 拒绝 `ALL service namespace not verified` | T529 使用单机 `ORDER_CLUSTER_ENABLED=false` 生成的 `ATSConfig.ini`，却拿来启动 A/B；ZK `/MDTService/OrderSvr` 仍是 `STANDBY` | 不复制旧单机 `ATSConfig.ini`；必须用官方生成器按目标模式生成 A/B 的 `SERVER.OrderSvrA/B`、`SERVER.TradeSvrA/B`、`LBConfig.*=Partition`，静态检查＋真实 ZK 类型检查全部 PASS 才允许启动。 |
| D03 | Home RSA 签发被 `COMMON_SIGNED_PREVIOUS_E1_PHYSICAL_DIR_INVALID` 拒绝 | 误把 E1 Birth/Genesis 当成业务恢复安装已经完成；真实 `transactions/Pxxx` 缺少 Snapshot、WAL baseline 和恢复 Ledger | 固定状态序列：**Birth → 原始双 RSA Genesis → 256 分区真实业务恢复安装（Snapshot/WAL/Ledger）→ 双节点 Home RSA → Common E1→E2 CAS → E2 业务 READY → Gateway**。每阶段有物理证据，缺失则停止。 |
| D04 | Home 刚退出，新恢复进程遇到 `recovering node lease owned by another ZK session` | ZooKeeper 旧临时租约尚未自然到期 | 先检查原进程停止和旧 ephemeral lease 消失，然后由 Common 正常领取；**不强删 ZK lease、不手工加 Epoch**。 |
| D05 | Spring Started，但业务不可交易；错误报告 READY PASS | 控制面 `E2|READY`、`businessServing=false`，或者业务网关尚未发布认证路由 | 明确区分 `Birth`、`Snapshot/WAL/Lease`、`E2 CAS`、`Started`、`Gateway TCP`、`认证 RPC`、`真实资金/订单/成交`、`自动 HA`。任何一项不能替代后一项。 |
| D06 | Common 升级后仍有旧 Projection JAR；启动首批出现 `1015`（是否由版本差异直接导致尚未证实） | 已证实 T532 Projection 镜像内仍是 `com.app.common-3.0.15.jar`，而 Order/Trade 为 T523 Common；更新四个业务节点并不自动更新所有消费者 | 所有运行中的业务与客户端共用完全一致 Common SHA，发布前运行 `check-common-jar-consumer-parity.sh`。T533 Projection 候选用只读挂载做兼容性验证，**最终仍必须重新构建正式镜像**。启动初期短暂 `1015` 不视为投影 PASS。 |
| D07 | APS `UnknownHostException: fstream.binance.com` | Colima 的 `--network host` 容器 `/etc/resolv.conf` 无 nameserver | 发布前运行 `check-host-network-dns.sh`；按部署宿主实际可用 DNS 配置容器，不将测试环境的 `192.168.31.1` 硬编码到产品。 |
| D08 | DNS 恢复后 APS WebSocket 依然无行情 | IPv6 `ConnectException`；改为 Java IPv4 后仍出现 `SocketTimeoutException`，可能是外部网络/区域策略 | 将 **DNS 解析 PASS、TCP 443、WebSocket 建立、有效行情收包、APS→MD 按 querysymbol 发布、TTL** 分开验收。禁止以 `subscribe* active` 日志算行情接收成功；无有效报价不得宣称 Robot/Tape 正常。 |
| D09 | Gateway 和四个节点都在线，但 Projection 新库水位依旧 0 | 无真实新交易；T533 已有 4×2 条 TCP 连接和 512/512 路由一致，但尚缺认证 Fetch RPC 成功及真实事件落库 | T533 已证明网络／路由**静态一致**，后续必须以新租户真实入金/订单/成交产生事件、验证 Fetch → Projection 事务及水位再判 PASS。严禁将旧投影水位直接导入新 Common 原始 WAL。 |
| D10 | 新装环境缺业务数据库迁移、资金/投影表现异常 | 历史曾发生安装时业务表/字段迁移遗漏，以及 JDBC 包版本回退；本轮未重新定位为主因 | 全新安装必须检查数据库迁移、实际 schema、JDBC 8 依赖、Order/Trade/Projection 使用同一数据库代际；发现错误先留证据、判别代码问题还是陈旧测试数据。 |
| D11 | Demo A/B 切换 PASS，替换成 Order/Trade 却不工作 | 跨服务恢复接口/Bean、业务原始 Snapshot 和配置接线可能未接入，而不是 Common HA 已通过即可自动证明所有 Spring 服务可运行 | **先在 Demo+Common 验证协议，再确保 Order/Trade 只实现 Common SPI；真实 Spring、Gateway 和业务数据链路单独验收**。不在业务服务内重写集群功能。 |
| D12 | 两节点各自 256 个 `business.wal` 文件就宣称复制和 HA 通过 | WAL 文件存在不等于存在真实客户端写入、对端持久化 ACK、自动主切 | 必须在实际写入时验证双节点原始 WAL/CommitIndex/ACK，SIGKILL 主节点、自动接管、旧主隔离、恢复追平、反向切换和业务最终一致性。STRICT 与 LOCAL 保障必须区分说明。 |

## 三、部署前必须执行的检查（可复制）

按 **目标模式**准备 `ENV`、`DEPLOY_ROOT`，不要把真实账号、MySQL 密码、RSA 私钥打印到日志或提交到仓库。

```bash
# 1. 生成新的正式 Gateway/业务配置；现在会自动执行 fail-closed 静态预检
./generate-saas-configs.sh "$ENV"

# 2. 启动 ZooKeeper 后，只读核对 ZK 中服务发现模式
python3 tests/preflight_saas_cluster_config.py \
  --env "$ENV" \
  --control-dir "$DEPLOY_ROOT/control" \
  --zk-container "$ZK_CONTAINER" \
  --zk-cli "$ZK_CLI"

# 3. 如果需要接入原始 Common E1/E2：检查所有阶段 Common 的身份/地址/端口
python3 tests/preflight_saas_cluster_config.py \
  --env "$ENV" \
  --control-dir "$DEPLOY_ROOT/control" \
  --runtime-root "$COMMON_STAGING_ROOT" \
  --zk-container "$ZK_CONTAINER" \
  --zk-cli "$ZK_CLI"

# 4. 在所有消费者 JVM 真正启动后，核对每个 Common JAR
bash tests/check-common-jar-consumer-parity.sh \
  "$APPROVED_COMMON_SHA256" \
  "$ORDER_A_CONTAINER" "$ORDER_A_COMMON_JAR_PATH" \
  "$ORDER_B_CONTAINER" "$ORDER_B_COMMON_JAR_PATH" \
  "$TRADE_A_CONTAINER" "$TRADE_A_COMMON_JAR_PATH" \
  "$TRADE_B_CONTAINER" "$TRADE_B_COMMON_JAR_PATH" \
  "$PROJECTION_CONTAINER" "$PROJECTION_COMMON_JAR_PATH"

# 5. APS 使用 host network + 外部行情源时，先查容器是否有 DNS
bash tests/check-host-network-dns.sh "$APS_CONTAINER"
```

- `preflight_saas_cluster_config.py`：只读检查目标单机/A/B 模式、Gateway 的 B 节点、RegType、Partition LB、ZooKeeper 注册地址、端口冲突、分区运行配置 namespace、实际 ZK `ALL` / `STANDBY` 服务发现类型。支持 **单机与双节点**，不会误将单机模式判成异常；可选实时 ZK 检查要求 ZK 已运行，且目标服务发现节点已被正式创建。若已有持久 `STANDBY`，不能盲目重复使用其旧 namespace；只对确认隔离、无实际业务子节点的开发环境进行审计式迁移。
- `generate-saas-configs.sh` 的 **内置静态预检**：已经接入，若配置不完整直接 exit 非零。不会检测已启动 JVM 的实际 RSA/ACK；此后仍需真实 ZK 和证据检查。
- `check-common-jar-consumer-parity.sh` 检查的是进程**实际加载路径**的 SHA，而不是镜像标签、Maven 版本号或本机某个 JAR。
- `check-host-network-dns.sh` 仅保证容器内有 nameserver，**不保证 Binance 网络能连通**。如果租户采用自定义价格源，按该数据源自己的 TTL、权限和端到端事件验证，不能依赖 Binance 网络条件。
- 每次检查失败不得直接跳过脚本或关闭 Common 安全门禁；记录错误字段、运行参数、出错容器、ZK 版本、对应 Common SHA 及是否存在真实数据。

## 四、按顺序发布，防止跳步

1. **确定单机还是 A/B、Fresh 还是 Upgrade**。Fresh 必须隔离 ZK namespace、MySQL/Projection 水位与 Common WAL 数据代际；Upgrade 必须先完成旧数据和 Replica 真实一致性审计。
2. **构建和验 SHA**。固定 Common JAR；Order/Trade/Projection/MD/其他 Common 消费者均使用同一已发布 JAR；不允许 Spring 类路径混用旧 Common。
3. **生成配置并预检**。单机生成单机；A/B 生成完整 A/B，Gateway、各业务服务必须使用同一生成批次；旧 ZK 临时租约必须自然失效。
4. **恢复出生证据**。E1 Genesis、各分区物理业务 Snapshot/WAL/Ledger、双 Home RSA、真实 E2 CAS，全程 Common 拒绝不合格恢复；不为了追求 READY 手工写入虚假证明。
5. **部署真实业务 Spring 和 Gateway**。Order A/B、Trade A/B 全部 `Started`，Gateway 真实 TCP、ZK ephemeral 所有权、512 分区路由一致；**这只是接线 PASS**。
6. **运行真实业务链路**。新租户申请、自动审批、正式 Broker API 开户/入金、Robot 自动报价/点价、Trader 下单、成交、撤单和平仓；逐一对照资金/持仓/订单状态/成交及 Projection/MySQL。
7. **最后再做真实自动 HA**。物理 A→B→A 互切及故障期间写入；禁止把手工改 Epoch、单纯两节点运行或静态 512 分区比对叫作自动 HA。
8. **负载测试后置**。10→50→200 租户 steady/burst 和 HA 注入在基础功能通过后进行，不应反过来阻塞基础交易部署；但不能省略最终容量和一致性验收。

## 五、一次失败需要留下什么

每次新部署或 Common 升级，至少记录：

- GitHub 分支／commit、各业务镜像 digest、**Common Jar SHA256**、最终 `ENV` 文件的路径（不记录密码内容）。
- 部署模式：单机还是 A/B，实际业务与 Gateway 的 `ATSConfig.ini` 来源，ZK 地址/namespace 与 `dataVersion`。
- 所有分区的 E1/E2/RSA/WAL/Ledger 水位和缺失列表；旧租约 `ephemeralOwner` 及自动撤权证据。
- 本机四业务容器、Projection、MD、APS、Gateway 的真实状态、日志中第一处失败、真实 TCP/认证 RPC 结果。
- 影响范围：是否已有真实资金/挂单、是否允许丢弃隔离测试数据、回退方案；修改前复现与修改后对照。
- 正确标记 `PASS`、`NO-GO`、`BLOCKED_BY_EXECUTION_ENV`、`NOT_TESTED`，不把它们混成“部署成功”。
- 若宿主磁盘告急先分析大文件、Docker 引用和真实数据保留策略；不得直接删除挂载中的 WAL 或旧主业务数据。

## 六、当前 T533→T534 基线（2026-11-07）

- 新隔离 Order-A/B、Trade-A/B 已完成 256 分区 E2 认证、Spring/Gateway TCP；T533 新 Projection 已连接四个业务 JVM，Common SHA 与其一致。
- 512/512 ZooKeeper 权威清单与物化路由一致，**不是复制 ACK 或自动 HA 测试**。
- T533 APS 已恢复容器 DNS，但 Binance IPv4 WebSocket 443 仍超时；真实标记价格与 Robot/Tape **NO-GO**。
- 新测试租户创建动作此前遇到平台执行安全检查，仍无可核验的正式资金入账、撮合、Projection 非零水位。
- T534 已在 Mac 上以实际 T529 单机和 T531 A/B 环境各成功运行新增配置预检；**8 项回归测试 PASS**，并将静态预检钩子接入配置生成器。下次部署**必须使用新版本生成器**。
- 当前结果：**Common A/B 服务认证启动 PASS；真实交易、投影一致性和自动 A/B HA 均 NO-GO**。

## 七、相关原始证据

- [T530 原始 RSA 与 Order 恢复](T530_FRESH_COMMON_RSA_E1_ORDER_RECOVERY_20261106.zh-CN.md)
- [T531 Order E2 与 Gateway A/B 根因](T531_ORDER_E2_REAL_GATEWAY_AND_TRADE_BLOCKER_20261106.zh-CN.md)
- [T533 Common JAR、DNS、512 分区比对](T533_COMMON_CONSUMER_JAR_DNS_AND_ZK_ROUTING_20261106.zh-CN.md)
- 新检查：`tests/preflight_saas_cluster_config.py`、`tests/test_preflight_saas_cluster_config.py`、`tests/check-common-jar-consumer-parity.sh`、`tests/check-host-network-dns.sh`。
