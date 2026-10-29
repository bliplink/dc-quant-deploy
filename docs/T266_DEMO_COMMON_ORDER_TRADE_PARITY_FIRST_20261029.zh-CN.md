# T266｜先验收 Demo+Common，再让 Order/Trade 完全复用（2026-10-29）

## 正式开发优先级（所有后续迭代必须执行）

**P0 仅开发 Demo+Common，必须完整真实验收底层 A/B 主切、单节点写入与副本恢复；P0 不通过禁止跳到 Order/Trade 修复集群。P1 只把已经通过的同一版 Common 运行时接入 Order/Trade，P2 再验证 Robot、Tape 和资金持仓/MD/Projection 全链。**

每次变更都先问：能否用 Demo 原样复现？如果是 HA 机制问题，补丁只能进入 Common，并先在 Demo 上真实验证；业务进程只可提供业务编解码、状态机和必要配置。严禁再次新增 Order/Trade 私有主切逻辑、单独的恢复账本和业务类型白名单。此优先级同时写入 `AGENTS.md` 与主架构规范。

## 结论
**不允许再为 Order/Trade 另造一套集群。** OrderSvr/TradeSvr 只实现业务 `byte[]` encode/apply/replay/snapshot；Common 独自提供单主分区、TCP WAL 复制、确认水位、快照/归档、成员租约监测、自动主切、单节点持久化降级、旧主撤权和副本回归追平。

本次真实差异不是 Common 解析了订单类型，而是 **相同底层 Common 的集成方式和自动故障恢复运行生命周期不相同**。

## 已复核的证据

| 项目 | 现存 Demo+Common | 当前 Order/Trade |
|---|---|---|
| 业务数据 | `DemoCommonBusinessAdapter` 不认识集群 | `Order/Trade` 业务状态自己编码 |
| Common 启动 | `CommonCertifiedNodeBootstrap.openAndStartWithZkFencingAndSources` | `CommonCertifiedNodeBootstrap.openAndStartWithZkFencingAndReplay` |
| 自动监测 | `DemoCommonLiveZkProcess` / `DemoCommonRejoinProcess` 测试进程中**显式构造并启动** `CommonCertifiedFailoverWatch` | Common/Order/Trade 主代码搜索仅发现 Watch 类的定义，**没有任何生产常驻调用** |
| 写入/降级 | T124–T130 可选 `LOCAL_DURABLE_ASYNC`、第三独立 RSA C 见证、A→B→A | 目前 Common 严格提交配合旧式配置中 `order/trade.cluster.failover.enabled=false`；无统一在线降级/恢复接线 |
| 二进制 | `t177` Demo 目标 jar SHA256 `87bdcb4d59cd71a19c5682dcac43317d6eded231e0c0bdeb6010b6adb3f24ac3` | Order/Trade 实际镜像 Common jar SHA256 `9d5a7944c25981245fe80d5df15d4287331e9e914392124e82dcec51d14dd401` |

这两个 Bootstrap 公共入口底层都最终调用 Common 的 `openAndStart`；不可简单以名字不同认定集群不同，**需要把成员/故障回调、READY/恢复、复制模式以及验收条件统一**。

Demo T120/T121 的显式自动 Watch 用例只验证自动 CAS 到下一 Epoch 的 `RECOVERING`，并拒绝虚假的 `READY`。T124–T130 的**扩展测试脚本确实包含**两次真实 SIGKILL、单节点本地写入、重新加入、反向认证等可选场景，但需要明确区分 `LOCAL_DURABLE_ASYNC` 与多节点 `QUORUM_DURABLE` 的保证，不能将其混称为严格 2/2 下不丢单。

## 2026-10-29 当前本地重新测试结果

1. T267 曾在 T260 Common Jar 上执行节点/主切/历史 WAL **JUnit 21/21 PASS**（未提供原始 RSA 的部分用例当时跳过）。T268 找回原始 A/B/C RSA 后，在正式 Docker Netty 运行依赖和新 Common 候选 Jar 上重新执行所有四套测试：**JUnit 21/21 PASS，原始 RSA 物理节点用例实际运行**。
2. 使用相同 jar 编译并执行 Demo `DemoCommonOnlyStateMachineTest`：**JUnit 1/1 PASS**，验证业务 byte[] 状态机、幂等、Snapshot/Restore 一致。
3. **T268 已重新发现并只读使用原始 Demo A/B/C RSA**，完成真实隔离三节点 ZooKeeper、两次 SIGKILL、A→B→A 自动进入下一 Epoch/独立 C 签名本地 READY 并继续业务写入：**T124–T130 全扩展 PASS**。B 在 Epoch 3 下再次回归未验证，且测试进程仍串联 Common 恢复/READY API，**P0 全自动生产生命周期尚未 GO**。具体实测和候选 Jar SHA 见 [T268 真实证据](T268_DEMO_COMMON_DUAL_SIGKILL_A_B_A_REAL_EVIDENCE_20261029.zh-CN.md)。
4. **T269：** 从 T268 保留的真实 E1/E2/E3 原始 WAL 和 RSA 在独立测试盘恢复旧 B 的 E3 物理复制，原始字节、A/B SHA/签名及业务总值 74/状态摘要均相同：**JUnit 1/1 PASS**。这是可追平能力，**B 在线自动加入和恢复 Replica READY 仍未验证**。见 [T269 证据](T269_COMMON_E3_B_REPLICA_PHYSICAL_CATCHUP_20261029.zh-CN.md)。
5. 真实 Order B SIGKILL 已在 T265 观察 FAIL：租约失效却未自动取代，存活节点 `P110/P180` 不可写；Order B 重启时 `Common physically fsynced WAL head mismatch`，Robot 暂停，保留原始证据。此次不应继续干扰已失败现场。

## 强制下一验收顺序（相同生产 Common 机制，不加第二套）

1. **先 Demo+Common：** 固定唯一 Common jar 的 SHA256；Demo 通过与 Order/Trade 生产环境一致的常驻 Common 启动和 Watch 机制；在实际双 JVM/真实 ZooKeeper/真实 TCP/WAL 上跑 A SIGKILL→B **真正 READY 并接受新业务写**→A 自动追平→B SIGKILL→A 真正 READY 并接受新写→B 追平。全程验证旧主隔离、签名提交水位和财务或 Demo 状态一致，不允许测试脚本在故障后代替系统手动执行切换。
2. **存活主写入：** 正常双节点优先物理同步签名；备节点丢失时 Common 按已定义清楚的本地持久化降级继续业务（标示不再具备副本零丢失保证），旧主必须撤权；不能依赖存活副本继续 2/2 ACK。
3. **再 Order/Trade：** 使用**同一个 Common jar、同一 Bootstrap 和常驻 Watch/恢复逻辑**；业务服务仅注入自己的状态机接口、服务名/节点名/分区/路径/端点/策略配置。禁止额外 Order/Trade HA、业务类型 WAL 白名单及新的认证子协议。
4. **再真实业务：** 租户注册、Robot 盘口与 Tape 真实成交、Trade 资金/持仓一致、MD 最近成交、Projection SQL 与 Common 认证日志一致；对业务服务 A/B 各做连续两次自动主切。只有全部通过才改为 GO。

**暂停扩展业务功能。** 当前优先级先恢复被证实的通用 Common HA 功能，而不是在 Order/Trade 上继续叠加修复和门禁；如需处理旧 WAL 数据，所有操作要有可验证的恢复水位和备份，不以手工清理代替自动恢复验收。