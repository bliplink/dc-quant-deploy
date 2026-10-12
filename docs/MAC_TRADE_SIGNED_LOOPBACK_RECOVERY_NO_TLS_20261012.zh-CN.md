# Trade HA：Host 网络下无需 TLS 的签名 Snapshot/WAL 恢复方案（2026-10-12）

## 已确认的现网架构与决定

Mac 24 服务 `dc-saas` 是 Docker **`network_mode: host`**，
Trade-A/B 的真实复制端口为 `127.0.0.1:19221/19222`。
服务之间可以直接通过回环 TCP 通信，**不需要 TLS，
不需要改 Gateway，也不需要扩大到 Docker 公网地址。**

此前尚未提交的 mTLS 试验已从 Common 工作区撤回，
`bliplink/com.app.common` 保持原来的 Netty TCP
和 HMAC 签名恢复协议，不新增 TLS/证书依赖。

现有 Common 验证包含：
- Trade 主节点基于**物理节点密钥**为 HEAD 和 Snapshot
  Manifest 提供 HMAC 签名、nonce/challenge 时效及 SHA256；
- 按真实 ZooKeeper 分区、epoch、ZK version 验证物理源；
- 仅传输已提交的 Chronicle WAL 后缀，
  最大4096 slot、恢复前校验二进制状态事件；
- Replica 验证完整镜像与 WAL 后在私有目录执行
  fsync + sealed image，不直接声明业务 READY；
- Replica 在独占分区锁内比较本地同步日志 marker 和源
  Snapshot 基线，权威持仓快照安装必须与本地 WAL 一致；
- Gateway 继续仅透传，没有任何改动。

**无 TLS 不等于取消 HMAC/签名/副本水位/epoch 验证。**
在当前单机 Host 网络前提下无需私有IP或证书；
未来桥接网络的私有IPv4能力是显式关闭的独立可选项。

## 本轮源码及验证

Trade 仓库 `bliplink/com.app.dc.tradesvr`
`codex/trade-safe-wal-archive-canary-20261012`：
`aed2f11e61631202e94bdc8083d5d0a0b5d416f8`。

新增 `TradeReplicaRecoveryPeerGate`：
- 默认仅允许 TradeSvrA/B 准确节点名的 loopback；
- 仅显式 `trade.cluster.recovery.replica.privateDocker.enabled=true`
  时，可使用 **数字字面量** RFC1918
  10/8、172.16/12、192.168/16 的私有IPv4；
- 拒绝公有IP、非RFC1918、名称重绑定、域名、
  其他集群节点，以及不合法port；
- 原分区 Assignment、epoch、source signed HEAD、
  Manifest、WAL commit / snapshot SHA 验证均保留，
  没有修改原有业务复制/ACK。

在本地精确固定 Common 6b8fe7d 镜像的 Maven 链执行
**Java8 `clean test` 292/292 PASS**，专项14/14。
新的不可变**本地候选**：

`dc-saas/tradesvr:cluster-dev-local-c6b8fe7d-20261012-signed-loopback-aed2f11`

Common Jar SHA256：
`34a6ee05db748eb2990f68b1dc86188a41ca52c320e1838b9cd82fd3c77a0363`。
镜像标签中 `dc.source.revision` / `dc.common.jar.sha256`
均已核对，**尚未编译为正式 GHCR 多架构发布镜像**。

## 部署脚本的完整可复用恢复开关

`generate-saas-configs.sh` 新增以下环境项：

```sh
TRADE_CLUSTER_RECOVERY_WARM_ENABLED=false
TRADE_CLUSTER_RECOVERY_NODE_KEY_HEX=
TRADE_CLUSTER_RECOVERY_PRIVATE_DOCKER_ENABLED=false
```

当前 Host 网络仅需设置第一项为 `true` 并提供
**独立生成、不要提交Git的随机32字节密钥**。
切勿把真实密钥放入部署文档或命令日志；密钥示例生成：
`openssl rand -hex 32`（输出写入私有0600 env文件）。

启用门禁：
- Trade cluster 必须开启，`replication.required=true`；
- Periodic Snapshot 和
  `TRADE_CLUSTER_SNAPSHOT_TRANSFER_AWARE_ENABLED=true`，
  默认每2048 WAL slots 提前完成完整 Snapshot，
  留出4096-slot 复制窗口余量；
- 节点物理密钥64或128位十六进制字符串；
- 必须为TradeA、TradeB创建**各自0700权限**
  `recovery-staging` 与 `recovery-sealed` 目录，
  绝不可共用；
- `trade.cluster.recovery.source.enabled`、
  `replica.headDiscovery.enabled`、`replica.stage.enabled`、
  `replica.install.enabled`、
  `replica.autoWarm.enabled` 必须全部同一次打开，
  不允许出现一端只开 Source、另一端没有 WAL检验的部署。
- 配置生成器在密钥缺失、无完整 Snapshot、
  缺失同步复制或无效开关时直接拒绝。
- 原业务复制、Order、Gateway、MD 配置不变。

`bash tests/test-trade-cluster-config.sh` 已通过：
含默认关闭、显式启用、A/B各自stage路径、
密钥缺失和Snapshot配置错误的负向验收。

## 现网为何尚未切换 Trade 镜像

Mac 当前在线A/B：
`dc-saas/tradesvr:cluster-dev-local-c6b8fe7d-20261012-archive-recovery-0e798cc`。
新代码已编译，但**A/B都尚未替换**。它们仍各担任
部分租户的 Primary，另侧就是必需的唯一同步Replica。
贸然重启可能造成 ACK 失去必需副本、交易员看不到
持仓或者需要十多分钟串行回放。

重启前必须先完成以下独立验证：
1. 在非生产端口通过真实Netty和真实物理Host回环
   验证签名 HEAD、Manifest以及完整单分区快照传输；
2. 确认 Replica 匹配当前epoch/状态及文件句柄
   generation fence，不用不完整Snapshot直接晋升；
3. 生成各分区签名水位/Replica持久证明，
   `tests/check_trade_live_snapshot_role_preflight.py`
   不能再是10/10 blocked；
4. 在经过授权的冷部署或有安全的第三节点排空机制后
   安装新镜像，验证真实持仓故障切换与回滚。

10户最新只读审计：
`PASS_10_TENANT_SNAPSHOT`、
每户Robot RUNNING、40笔订单、双边十档，
**24容器全部运行且TradeA/B无重启或OOM**。

## WAL归档/删除关系

Common `c196fec` 已实现
`PREPARED → QUARANTINED → REMOVED`
持久化回收事务和隔离文件fsync/sha256验证，
`248/248` Common 单元测试通过。
**安全回收仍需服务端持久Replica完整Snapshot与
Projection watermark等权威证明，不是启用恢复链路
就能立即删除旧 WAL。**
Mac 当前初始化归档512目录、48小时到期候选0，
用户业务 WAL 删除仍未开启。
