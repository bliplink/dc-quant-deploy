# T268｜Demo+Common 单一运行时 A→B→A 真实 SIGKILL 验收（2026-10-29）

## 结论与阶段门禁

**P0 已通过真实隔离 Demo 两次自动主切及恢复写入的阶段验证，尚未达到完整 P0 GO。** 已验证 A→B READY、本地持久化继续写入、A 回归 E2 追平、B→A READY 和 A 本地持久化继续写入；**缺 B 再回归 E3 追平及将测试进程中的恢复/READY 编排全部改用 Common 生产节点生命周期**。因此不得据此直接更新 Order/Trade 镜像或宣布业务 HA 通过。仍遵循强制顺序：P0 Demo+Common → P1 Order/Trade 原样接入 → P2 真实交易/MD/Projection。

### 本次实测使用的真实组件

- 隔离 Docker JVM、真实 3 节点 ZooKeeper、TCP/Netty、真实物理 WAL + RSA Genesis 和 Custody，旧 A/B/C 原始密钥以只读方式加载，**未生成新身份**。
- Common 唯一候选 Jar SHA256：`73de80a0725208b3fde88b04c8f8f8b0601ffeb6d71b4de36f7e98cd018b1282`，来自原 T260 Common Jar 加本轮 `CommonCertifiedNodeRuntime` 最小改动；尚未发布成正式依赖，**不能与当前 Order/Trade 正式镜像声称 SHA 相同**。
- Common 源码独立本地分支提交 `14d1b08 fix(common): own replica failover watch within certified node runtime`。没有新增恢复协议、额外账本、业务类型白名单或单独 Order/Trade 集群。
- 原始隔离运行证据：`~/.opentradingcore/t268-common-only-sigkill-runs/20261029085715`（T124），`~/.opentradingcore/t268-common-only-sigkill-runs/20261029085859`（T124–T130 全程）；仅在 Mac 本地保存原始证据，**不上传私钥、RSA 完整证据或 live WAL 到 GitHub**。

## 实际 PASS 记录

| 真实测试 | 实际结果 |
|---|---|
| A/B 各自真实 RSA 双 Genesis 签名、fsync、重新打开 | T124 PASS |
| 原生 TCP 复制、双方 RSA Quorum ACK、初始业务总值 40 | T124 PASS |
| 业务 Primary A 真实 Docker SIGKILL，B Common watch 在故障前已启动 | T124 PASS |
| B 自动 CAS 到 Epoch 2 RECOVERING，验证旧签名历史、WAL、业务总值 40 | T124 PASS，尚未 READY |
| 独立 C 长期见证、发布独立 E2 切换签名，B 到达 Epoch 2 LOCAL READY | T130/T125 PASS |
| B 在 A 故障时本地 fsync 新业务，Demo 总值 40→60 | T125 PASS，LOCAL_DURABLE_ASYNC |
| 旧 A 真正重新加入，复制 B 的 E2 WAL，独立 A RSA 收据并比对状态总值 60 | T126 PASS |
| 已追平的 A 提前启动反向 Watch，主节点 B 真实 Docker SIGKILL | T127 PASS |
| A 自动 CAS 到 Epoch 3 RECOVERING、跨 Epoch E1+E2 WAL replay，状态总值 60 | T127/T128 PASS |
| 独立 C 长期见证 E3 切换，A 获取 Epoch 3 LOCAL READY | T130/T129 PASS |
| A 在 B 故障后新增真实业务，状态总值 60→74、6 个去重请求 | T129 PASS，LOCAL_DURABLE_ASYNC |
| Docker 正式 Netty/依赖、原始 RSA 下 Common 节点/协调器/历史 WAL 的 JUnit | **21/21 PASS**，约 54 秒 |

本次 T124 快速独立复测也通过，证明在没有单节点放权条件时系统只进入 `RECOVERING`，拒绝无证明的 READY 与业务写入。

**保证边界：** 两次故障期间采用独立 C 见证的 `LOCAL_DURABLE_ASYNC`，只有存活节点本地 fsync、明确存在 RPO 风险；不是 `QUORUM_DURABLE`。不允许将单节点继续工作的业务结果谎称为跨机器无丢失或把既往 local ACK 追认成 quorum ACK。

## 本轮最小 Common 代码变化（仅复用已有机制）

1. `CommonCertifiedNodeRuntime.armAutomaticFailoverWatch(partition, coordinator, pollMillis, catchup)`：必须节点已启动、分区确实为本机 Replica、角色授予仍有效且没有重复 Watch；在 **Common runtime** 内创建、启动和持有原有 `CommonCertifiedFailoverWatch`。
2. 节点关闭先关闭自己持有的 Watch，再关闭 Netty 和 WAL；不会制造 READY、没有新认证/RPC/持久化流程。
3. `DemoCommonCertifiedService` 仅委托上述 Common API；原先 `DemoCommonLiveZkProcess` 自己 `new CommonCertifiedFailoverWatch` 的代码改为委托。T124–T130 的真实隔离故障链路按这个接线通过。
4. 脚本 `verify-real-auto-sigkill-genesis-replay.sh` 支持只读指定候选 Common Jar，确保当前测试的二进制与源码更改准确对应，而非复用之前旧 Jar。
5. 测试后 Common 分支干净，4 个源码/脚本文件在提交 `14d1b08` 中；没有改 Demo 真实业务计算、Order/Trade 业务进程或其故障数据。

## 尚未完成的 P0 必过项

- **B 第二次回归：** 完成 Epoch 3 下 B 重启、从 A 自动恢复 E3 已确认 WAL 和业务 Snapshot、追平验证，并能恢复双节点常态。T129 验证到 A 继续写，但没有验证 B 后续回归。
- **Common 生产生命周期：** 当前测试程序仍在 Watch 产生 RECOVERING 后调用现成 Common Genesis/WAL Replay、C 外部签名核验、`publishCertifiedDegradedReady` 等 API。必须将这些步骤和现有 Common runtime 串联为业务无关的自动恢复生命周期，Demo/Order/Trade 只提供自己的 `byte[]` apply/snapshot 回调。不能用测试程序代替生产 READY 自动流程。
- **严格模式和窗口：** 验证原主未隔离时绝不双主；正常 RF2 双节点 `QUORUM_DURABLE` 的故障切换和重启尾部安全收敛；从本地 ACK 恢复双副本时不伪造历史 Quorum。这些仍需在完全无人干预 Demo 上通过。
- **P1/P2 不提前：** 暂不改写已有 Order/Trade/WAL 故障证据，待 P0 完整 GO 后只替换统一 Common 二进制和通用接线，才验证新租户 Robot、Tape、资金/持仓、MD recentTrades、MySQL Projection 与 Order/Trade A/B 连续真实 SIGKILL。

本文件是实测证据及门禁，不是另一个恢复协议。优先级见 `docs/ARCHITECTURE_SIMPLE_COMMON_BOUNDARY_20261029.zh-CN.md`。