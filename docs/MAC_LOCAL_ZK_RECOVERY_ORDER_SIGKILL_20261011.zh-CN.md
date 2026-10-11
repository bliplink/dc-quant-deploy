# Mac 本地新 HA 集群冷部署与 Order SIGKILL 验收（2026-10-11）

## 适用范围
仅 Mac mini / Colima 的独立、可丢弃 **dc-saas Demo**。未修改 GHCR 生产发布锁，没有向 Maven Central 发布 Common。本轮冷重置只处理 Docker Compose `dc-saas` 的 24 个成员，不影响其他 Docker 项目。原运行目录安全移入 `~/.opentradingcore/.dc-saas-quarantine/dc-saas-runtime-dev-20261011-20261011T075418Z`，未删除；独立 P246 故障证据仍保留。

## 源码与镜像一致性

- Common：`3e1d45c693b8a11d06f90a4a78b02d984767a9b5`，修复初始 ZooKeeper 连接可能早于监听注册导致缓存 `connected=false` 的竞态。仅实际 ZooKeeper `CONNECTED` 可授权写入控制面；`CONNECTEDREADONLY` 不可选主。
- OrderSvr：`239f765ee325554bccfa8ff3effb6fbb5b8e132f`。
- TradeSvr：`0ad5191b884174a5c78a9d95976de675eeffa686`。
- MDSvr：`bcdec888a847462c6bd74da1014523bdc27c03d3`。
- GW：`6a84739d2149da0eaaf1ea64f485a2a19843f78d`。
- com.app.dc：`2fa804757c561fc9bbd0642a5c2153fca55cf286`。
- 本地镜像标签：`cluster-dev-local-c3e1d45c6-20261011075101`（GW、Order、Trade、MD 四组一致）。
- 嵌入 Common JAR SHA-256：`45ea321a89b44639310f6dd10ac043df144b2be05e8d8c087c0ccba2c01ea6c7`。
- 本地证据与配置：`~/.opentradingcore/local-ha-zkfix-20261011-v1/artifacts/`，新运行数据：`~/.opentradingcore/dc-saas-runtime-zkfix-20261011`。

## 实测结果

1. Common 针对性 ZooKeeper 测试 6/6；Common 全量单测 **164/164 PASS**。
2. Mac 本地镜像构建四组成功，dev 镜像锁校验成功；部署脚本镜像锁/发布锁测试通过，Mac 部署单测 10/10。
3. `deploy-saas-macos.sh --full-cluster --skip-pull` 退出码 0，24 个容器启动；前端 5 个健康检查通过，Gateway 和后端路由正常。Order A/B/C 业务端口 33036/33041/33044，复制端口 19121/19122/19123；Trade A/B 业务端口 33037/33046，复制端口 19221/19222。
4. 冷启动 Order、Trade 均 **256/256 READY**。故障前的完整 Order 分区/快照验证通过，128 个 Primary 位于 A，128 个位于 B，C 是所有分区的同步副本；256 组 Snapshot 一致。
5. 交易回归：租户 `OET72U` 自动审批、默认 Robot 20 买 + 20 卖持续挂单、自动流动性、入金、IOC 开多 0.0001 BTC、成交与持仓核对、Reduce-Only 平仓至 0、挂单清零、Robot 补单全部通过。
6. 受控真实故障：Order A `SIGKILL`，租户 `OET72U` 的 BTCUSDT 映射 `P238`，初始 `epoch=1`、A Primary、B/C 同步副本。**54.087 秒**后自动变为 **Order B Primary（epoch=2）**、C 同步副本、A Learner；B `ORDER_PARTITION_PROMOTION_READY` 和故障后市场盘口 10 买/10 卖均通过。Order A 重新启动，Docker `unless-stopped` 策略恢复。
7. 自动副本修复 `ORDER_AUTO_REPLICA_REPAIRED partition:P238 learner:OrderSvrA` 有明确日志；故障后再次运行 256 分区状态和 Snapshot 校验，**256/256 READY，256/256 Snapshot 一致**，Order B 持有 256 Primary，Order A/C 为同步副本，A/B/C 无 OOM。
8. 故障后新租户 `Y0ZJ1J` 再次完成 Robot、入金、IOC 开/平、成交/持仓一致性回归，PASS。

故障注入证据 JSON：`~/.opentradingcore/local-ha-zkfix-20261011-v1/artifacts/order-p238-sigkill-20261011T080859Z.json`。本轮测试脚本：`tests/run-mac-demo-order-sigkill.py`；只允许明确设置 Demo 租户、分区、确认值以及预验证的本地镜像锁，异常时尽力自动恢复被 kill 的节点和重启策略。

## 仍需验收（不得标记完成）

- Order B 持有全部 256 Primary，**自动恢复副本 ≠ 主分区自动再平衡**；压力测试前须明确再平衡/迁移策略。
- Trade Primary 故障注入、持仓恢复、旧日志 Archive Catch-up、Trade A/B 角色反转未在本轮实测。
- 尚未完成 10/200 租户持续运行和性能压测，也未做端到端的**故障期间每笔请求审计与严格零丢单/零重复成交证明**。
- 自动选主耗时 54 秒，需进一步拆分检测、租约过期、恢复门禁和路由恢复的延迟预算。

本验收记录仅报告已经由执行结果/日志证实的项目；不是生产 HA 发布签字。