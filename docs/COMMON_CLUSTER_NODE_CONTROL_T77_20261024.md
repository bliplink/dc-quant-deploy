# T77 — Common 节点级分区内存授权与双 ACK 策略接入（2026-10-24）

## 结论和上线边界

**Common 公共层已新增支持 256 分区的节点级授权快照与控制更新器；严格/异步两种策略在隔离的真实 P000 双 JVM 上完成了 WAL、ACK、故障与重启验收。本轮属于“公共机制+单分区真实端到端 PASS”，不是“256 个真实分区+Order/Trade 正式联动 PASS”。**

### 正式 `com.app.common` 源码提交

仓库 `/Users/kong/.opentradingcore/common-batch-official-release-20261013/common` 的 `saas-crypto`：
- `622ee53` `NodePartitionGrantTable`：一份经验证的节点授权批次原子安装256个 Partition 路由/角色/独立 Epoch/ACK 模式；Java8不可变内存快照，节点级期限、同 Epoch policy/owner 变更拒绝、Watch撤权、旧主退休 NotBefore、再认证、ACK证据校验；业务读/写/签名/ACK使用内存，不调用任何 ZK API。
- `0a219a2` `NodeClusterControlManager`：统一 `ControlPlane.renewNodeLease(node)` 接口，一个控制事件更新整批分区，而不是对每分区分别续租；节点Watch触发内存撤权，单独后台线程续期，失联后租约自行到期，不向客户端签发无授权 ACK。真实 ZK 验证与旧主隔离由注入 `ControlPlane` + `ControlVerifier` 实现，**该公共接口本身不假装验证任何密码学证明**。
- 官方 Common Java8 JUnit：`NodePartitionGrantTableTest` 8项 + `NodeClusterControlManagerTest` 3项，**11/11 PASS**，256个分区包含严格和异步两模式，超过20万次业务热路径验证期间控制验证器调用次数保持1；验证过期、拒绝旧Epoch续权、错签、错模式、租约世代变化、Watch撤权和退休屏障。
- 这些是**本地 Git 提交**，未发布中央 Maven、未执行 GitHub Actions、未推送。

### V19 真实隔离适配

非Git试点 `common-ha-netty-v19-control-cache`:
- `DemoV19NodeGrantBridge` 将当前 ZK CAS 授权过的 **P000** 本地 grant 转成 Common `NodeClusterControlManager` 的节点级批次；模式由持久配置 `DEMO_V19_ACK_POLICY` 决定。**这是试点适配，仍使用旧 `DemoZkLeaseController` 为 P000 获取授权，尚未以单个真实 ZK node-scoped Znode 更新256分区。**
- `DemoPrimaryWriter` 对每次 WAL 写入前检查新 Common 许可，严格模式的逐笔和 GROUP、异步本地模式都在成功 ACK 之前核验实际模式、持久化证据和内存许可，并继续独立校验旧有 `DemoHotpathControl` 租约；不绕过严格模式双物理 WAL fsync、双 RSA 证明、Common CommitIndex、两独立 Custody落盘。异步ACK只承诺本地 fsync并显示RPO风险。
- `DemoV19ClusterHarness` 通过单开关 `DEMO_V19_NODE_GRANT_TABLE=1` 启动节点控制器/注入 writer；未开启时沿用既有模式。
- `DemoV19Rf2StrictAssignmentCache` 已采用 Watch 通知刷新 +1.4秒低频兜底、2秒时间边界（T76连续改动），仍是 P000试点；不能当成生产256分区最终控制面。
- Java8实装编译通过，27/27项原有 V19严格恢复回归 PASS。

## 真实双 JVM / 3 ZK 结果（同一 Mac 上 Docker，单 P000）

| 场景 | 客户端成功 | 结果 |
|---|---:|---|
| 严格模式启用新表，A为Primary逐笔12请求并发3 | 12/12 | 3.467 WAL/s, P95 1158ms, seq1604→1616 |
| SIGKILL严格Primary A，B进入Epoch6，A恢复后Epoch7双签名+双Custody READY，B逐笔并发4 | 20/20 | 2.874 WAL/s, P95 2071ms, seq1616→1636 |
| 严格Epoch7，12批×32条、并发4 | 384/384 WAL | 105.717 WAL/s, P95 每批1575ms, seq1636→2020, A/B WAL和State SHA相同 |
| 两台数据JVM重启后严格客户端新写入 | 1/1 | Epoch7 seq2021，真正`QUORUM_DURABLE` |
| 切换到复用 Common `NodeClusterControlManager` 后严格逐笔并发2 | 8/8 | 2.087 WAL/s, P95 2038ms, seq2021→2029 |
| 异步模式新ZK/WAL卷，A逐笔30请求并发4 | 30/30 | 97.166 WAL/s, P95 89.64ms, seq0→30 |
| SIGKILL异步备节点B，A继续处理20笔并发4 | 20/20 | 71.784 WAL/s, P95 85.134ms, seq30→50；B返回自动追平，双方WAL/State SHA相同 |
| 双JVM重启后异步写入 | 1/1 | seq51，`LOCAL_DURABLE_ASYNC`, `quorumDurable=false`, RPO风险为true |
| 接入正式Common NodeClusterControlManager后异步逐笔12请求并发3 | 12/12 | 63.265 WAL/s, P95 93.603ms, seq51→63 |
| 异步中断3个ZK中的2个，等待9秒再写入 | 0 ACK（预期拒绝） | 客户端503：`missing, revoked or stale quorum grant`，没有使用失效旧租约发出伪造本地确认 |

12组32条只是每组一个Netty请求；不是384个独立客户端网络RPC。TPS仍远低于每分区1–2k和严格端到端5–10ms目标。单机不同CPU队列/JIT影响明显，不能把局部差异当作稳定性能收益。

## 尚未完成的关键任务，不能宣称平台HA全部PASS

1. **真实256分区 ZK 节点级快照适配**：Common逻辑已支持256，但真实试点依旧只有 P000、旧每分区450ms ZK控制验证。必须以节点级授权 Znode 或原子NodeGeneration +分区配置批次替换旧试点，实现 O(节点数) 续约，而非 O(节点数×分区数) 的ZK查询。需要实际测量ZK QPS。
2. **ZK多数派失联再恢复的安全新Epoch自动授权**：此前T75确认旧Grant撤销后同Epoch不可重获，ZooKeeper回归后仍需从物理双Custody/CommitIndex取得真实已确认水位、先隔离旧主，再CAS新Epoch后发READY，严禁简单清除撤权。
3. **复制和提交吞吐**：GROUP WAL/双Custody/CommitIndex有固定RSA与fsync成本，高并发尾延迟仍达秒级；需组提交、连续TCP流、复用物理Signer而不能降低签名可靠性。
4. **多物理节点/多分区和Order+Trade真实状态机**：当前A/B是同一Mac不同JVM，未在独立故障域跑256分区真实自动主切、10→50→200租户、真实撮合、资金/持仓/委托/成交及Projection对账；正式服务未部署本轮新Common。

## 交付证据

- 正式Common源码本地提交：`622ee53`、`0a219a2`（`saas-crypto`）。
- 部署文档：`docs/COMMON_CLUSTER_NODE_CONTROL_T77_20261024.md`。
- 完整源码归档：`tests/patches/common-node-control-both-ack-t77-20261024.tar.gz`、同名 `.sha256` 校验清单。
- 实验结束，`otc-t75-fresh` 与`otc-t77-local` 两套测试容器全部停止，合计16个独立ZK/WAL证据卷保留；正式Demo `dc-saas-*` **24个容器持续运行**。无GitHub Actions、无推送、无线上替换。
