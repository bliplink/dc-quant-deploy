# T531｜Order A/B E2 真实业务接入、Gateway A/B 配置修复和 Trade 恢复阻塞（2026-11-06）

## 执行判定

**Order A/B Common 认证业务启动与 Gateway 接通：PASS。** 已在 Mac 现场完成真实 Order 256 分区 E1→E2 ZooKeeper CAS；两台独立 JVM 均通过 Common 业务恢复与认证路由检查，Spring 启动成功，Gateway 实际 TCP 与 ZooKeeper 会话节点均已连通。

**Trade A/B 真实恢复、全链路资金和成交、自动 HA：NO-GO。** Trade 原始 E1 Birth/Genesis A/B 256×2 PASS，但其业务 `*.recovery` Ledger = 0。此前请求启动 Trade A/B 真实安装过程被平台安全检查阻止，本轮没有绕过这项限制，也未伪造 Snapshot/WAL/ACK。没有发出真实用户交易请求，未进行虚假的自动 HA 验收。

### 已验证状态

| 阶段 | Order A/B | Trade A/B |
| --- | --- | --- |
| E1 `STRICT_QUORUM|RECOVERING` 原始 256 分区 | 两份真实清单/出生 PASS | 两份真实清单/出生 PASS |
| 原始双 RSA Genesis seal | PASS | PASS |
| 原始业务 `journal/baseline.properties`、`sealed/*.snapshot` 和 `ledger/*.recovery` | 每个节点 256/256，真实磁盘复核 PASS | 0 份，NO-GO |
| 256 分区原始 Home 双 RSA 签发 | A/B 均 `COMMON_ORIGINAL_HOME_E1_PHYSICAL_RSA_FSYNC_PASS` | 未执行 |
| 真实 Common E1→E2 认证 CAS | `COMMON_ORIGINAL_FIRST_E2_READY_CAS_PASS` | E1 原版，未执行 |
| 从 ZK 再读全部分区 | `NPC1\|2`，dataVersion=1，256/256 Epoch 2 `STRICT_QUORUM|READY`，0 异常 | 还没 READY |
| Common Gateway 原始业务 Spring | `otc-t531-order-a-e2-abcontrol`、`otc-t531-order-b-e2-abcontrol` 都 `Started OrderSvr`，持续运行、0 重启 | 未启动 |
| 认证服务发现与实际连接 | `COMMON_GATEWAY_DISCOVERY_CERTIFIED`，端口 47522/47523、43036/43041 连通；Gateway 已真正连接两节点 | 未发布 |
| 认证现金入账、撮合、Robot、Projection、A→B→A | 均未通过 | 均未通过 |

## 关键根因与处理

1. **Home 签发实际完成。** 重新启动 `otc-t530-order-a-home` / `otc-t530-order-b-home` 两个 Common 真实恢复进程；两边分别对 256 分区签名，物理 `otc-t530-born` 数据卷中有 `original-home.v1`（6472 字节）及 A/B 两份 256 字节的独立 `*.original-home.rsa`。原 Home 进程随后停止，临时 ZooKeeper Lease 自然到期。
2. **旧 ZK 租约未到期导致一次正确拒绝。** 在 Home 刚停止后，过早重启 Order-B 原始恢复监听收到 `recovering node lease owned by another ZK session`；没有强行清理 Lease。等待 ZK 实际显示 A/B 两个旧临时节点都消失，B 重启后通过真实 Common 认证并监听 47323。
3. **Order E1→E2 物理切换完成。** 由 Order-A 使用 `config-stage/order/A` 的 `stageOriginalFleet=true` 通过 Common 自有恢复与原始第一 READY CAS；日志 `COMMON_ORIGINAL_FIRST_E2_READY_CAS_PASS service=OrderSvr partitions=256 signedGenesis=true businessServing=false`。A 阶段进程 exit=0，旧 E1 B 监听因状态撤权退出。ZooKeeper 再读证明 `NPC1|2`、dataVersion=1、256/256 Epoch2 STRICT READY；这一关是控制面 PASS，**不能单独算交易 PASS**。
4. **最初 E2 业务启动失败的真实原因已更正。**
   - Order-A 当时 `COMMON_GATEWAY_E2_READY_DISCOVERY_FENCED` / `Common Gateway original ALL service namespace not verified`；并不是 Trade 尚未 READY，而是 T529 最初用 `ORDER_CLUSTER_ENABLED=false` 创建了 ZooKeeper `/MDTService/OrderSvr=STANDBY`，Common 自有发布接口明确要求 `ALL`。
   - Order-B 原先端口 80 `BindException`，因为旧单机 `ATSConfig.ini` 缺 `SERVER.OrderSvrB` 配置；这不是业务复制端口冲突。
   - 先用**原正式配置生成器**单独生成 T531 新 `ATSConfig.ini`，明确 `ORDER_CLUSTER_ENABLED=true`、`TRADE_CLUSTER_ENABLED=true`，得到真实 A/B 各自服务端口、`ProtoVersion=2`、`SERVER.OrderSvr.RegType=0`、`SERVER.TradeSvr.RegType=0`。新独立控制目录 `~/.opentradingcore/t531-gateway-cluster-control/control`；没有覆盖旧 T523/公网 Gateway。
   - 切换到新隔离 Gateway 容器 `otc-t531-fresh-gateway-cluster`（43000/43001/43002），核对旧 `/MDTService/OrderSvr` 为无子节点、持久类型 `STANDBY`、version=0。仅对**这个 T529/T530 独立 ZK 的服务发现元数据**通过带 expected version=0 的配置迁移将其变成 `ALL`（新 ZK `TradeSvr` 初始已经为 `ALL`）；**没有修改** `/otc/t530-fresh-20261106-r1/order/manifest`、授权 Epoch、RSA、WAL、租约或客户资金。
   - 使用正确 A/B 控制目录启动全新 `otc-t531-order-a-e2-abcontrol` 与 `otc-t531-order-b-e2-abcontrol`。日志均记录 256 认证路由 PASS、`COMMON_GATEWAY_DISCOVERY_CERTIFIED` 及 `Started OrderSvr`。新 Gateway 的 `GWApi connectionListener onConnected server:OrderSvrA/B` 也两条 PASS；4/4 端口（47522/47523、43036/43041）物理 TCP CONNECTED。
   - 在新 ZK 直接读出 `/MDTService/OrderSvrA/OrderSvrA` = `Host:127.0.0.1,Port:43036,Stat:1`、`/MDTService/OrderSvrB/OrderSvrB` = `Host:127.0.0.1,Port:43041,Stat:1`，两条都有非零、不同的 `ephemeralOwner`。新 Gateway 到 Manager 正式转发请求返回真实参数校验 `9004`，非离线 `9000`。
5. **新 Order 实际 E2 WAL**：只读检查 `otc-t530-ready-data`：Order A/B 各有 256 份 `epoch-2/business.wal`；由于尚无新租户和新客户交易，不能把文件数量算成持久化成交或一致性 PASS。

## Trade install 前只读核查

- `config-install/trade/A`、`B` 各有准确的 256 个物理 `durableTransactionRoot`，都指向**新** `/srv/dc/data/t530-born/TradeSvr/TradeSvrA/B/transactions/Pxxx`；`*.common.control.zkHosts=127.0.0.1:42181`、`freshE1.namespace=/otc/t530-fresh-20261106-r1/trade`、`phase=RECOVERING`、`installFencedFreshGenesis=true`、`stageOriginalFleet=false`、`gatewayDiscovery.enabled=false`。
- `otc-t530-born` 实际有 Trade A/B 各 **256 个预备事务目录**、各 **256 份独立原始 RSA 出生收据**，但 `*.recovery=0`。目录不是成功证据；还必须由真实 Trade JVM 调用 Common 安装器写入 256 份原始业务 Snapshot、WAL baseline 和 Ledger 并认证一致性。
- 因此前 Trade 物理安装过程被 OpenAI 执行环境安全检查拦截，本轮严格停在只读预检。**没有尝试通过修改认证代码、假写成功文件或绕过安全检查放行交易**。

## 现网与剩余步骤

- 独立 MySQL `otc-t529-fresh-mysql` 端口 34306 仍是 **0 租户、0 Order/Trade 投影水位**。新 ZK 42181、新 Gateway 43002、Login/Manager/Admin 正常；T531 Order A/B 已注册。
- 旧 T523 Order/Trade A/B 仍单独运行在其原始 Common 命名空间和数据卷上，不替换旧容器。旧 Robot 和旧 Projection 继续停止，避免历史资金/水位错误写入新环境。
- **下一唯一前置门禁：** 正常许可条件下执行新命名空间 Trade A/B 原始业务持久化恢复 256×2，核验真实 Ledger/原始 Snapshot/零 ACK WAL → Trade A/B 原始 Home 双 RSA → Common E1→E2 认证 CAS → Trade A/B 正式 Gateway 发布。
- 之后才是正式的新租户自动审批、认证 cashIn、Robot 盘口与 Tape、限价/市价成交、余额/持仓/订单与 Projection 一致性；最后实际 A→B→A 自动 HA 和故障中持续写入。
- **当前实测结果是 Order A/B 认证 Spring+Gateway PASS，完整业务成交与 HA 仍 NO-GO。** 不以 “Order JVM Started” 作为项目完成。

## 核查路径

Mac 本地只读证据：`~/.opentradingcore/t530-common-boot-20261106-r1/evidence/`、`otc-t530-born`、`otc-t530-ready-data`；业务容器 `otc-t531-order-a-e2-abcontrol` / `otc-t531-order-b-e2-abcontrol`；官方 A/B Gateway 配置 `~/.opentradingcore/t531-gateway-cluster-control/control/ATSConfig.ini`。任何含密码和 RSA 私钥的本机私有配置都不得进入 GitHub。