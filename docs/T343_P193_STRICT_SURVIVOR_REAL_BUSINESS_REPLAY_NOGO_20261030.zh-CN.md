# T341–T344｜P193 原始 RSA-Custody STRICT 存活副本恢复、Order 混合事件回放审计（2026-10-30）

## 范围和真实现场

- 以 `saas-crypto` 统一架构为前提：Common 只负责 WAL、字节级认证、快照、复制、ZK 权限和自动主切；Order/Trade 的业务状态机各自解释已认证原始 `byte[]`，不能新增服务私有集群。
- 当前真实 ZooKeeper `/otc/t318-virgin-20261029-r1/order/manifest` 显示 `NPC1|2`，`P193|2|OrderSvrB|OrderSvrA|STRICT_QUORUM|READY`，A/B 原 ZooKeeper 临时租约都存在。**控制面 READY 不代表 P193 实际可以写。** B 原始物理 WAL 22668 条、CommitIndex/Custody 只认证 22667 条，P193 writer 被隔离，Robot 停止。
- Docker 进程 `-Dorder.common.nodeRuntime.dataRoot=/srv/dc/data/t330-fresh/OrderSvr/OrderSvrB` 覆盖了磁盘 properties 里的旧 `t319-ready-v4`；因此使用的 `t330-fresh` 确实是当前现场真实物理 WAL，避免跨代误读。

## T341｜Common：完整历史分窗口恢复

- 修复 `CommonCertifiedStrictCrashPrefix.inspectReadOnly` 原依赖 `readCertifiedFrames` 把 4096 当作整个历史上限的问题。
- 新 `CommonFileBusinessWal.readHistoricalCommittedWindows` 以每窗口最多 4096、完整返回数据最多 64 MiB 为上限，在原只读 WAL 上逐帧核对 sequence + CRC + 累计签名前缀 SHA，不采用多余物理后缀。
- 真实 P193 严格 B→A 方向：复用原 `OrderSvrA` 存活副本持久化的独立 RSA Custody/Receipt，加上 B/A 原始 WAL，通过 `CommonCertifiedStrictCrashPrefix`：**22667 认证、B 原 22668 未认证不进入恢复**。原件逐字节保留。
- Common commit **`04f3e25`**，本地 Common Maven 全量 **153 suites / 654 tests / 0 failures / 0 errors / 62 skipped**。真实 P193 原始 RSA 测试独立指定数据路径执行，通过且 0 skipped。

## T342–T343｜Order：原始业务回放和 Outbox

- 原始 P193 22667 条 E2 Order WAL 的真实事件：`STATE_UPSERT` 13147、`STATE_BATCH_V1` 3572、`STATE_ATOMIC_MATCH_V1` 1724、`STATE_MATCH_SETTLED_V1` 1724、`STATE_REMOVE` 2500。
- 旧 `OrderRecoveryStateMachine` 只能识别单状态 UPSERT/REMOVE，且 4096 上限；现在改为复用同项目既有 `OrderSignedStateFrameCodec.decodeAndValidate`，在 Common 已认证前提下解码全五类事件；`MAX_BATCHES` 提升为有界 65536 个业务变更，逐 WAL 记录要求严格连续的 `sequence`。
- 原子撮合与结算标记从原始带签 WAL 共同重建已有 `OrderCertifiedMatchOutbox`（不是新持久化系统），旧单纯一次性 Order 状态不能替代 Trade 资金证明。修复 Outbox 对 E3+ 原历史事件的 `epoch==2` 硬编码。
- **原始 E1 P193 快照 + 22667 条 E2 WAL** 的 Order 实际业务编码解析测试 `OrderT343RealP193ReplayReadonlyTest` 指定原件路径实际执行 **1/1 PASS、0 skipped**。隔离测试业务回调统计及 Outbox 校验都通过；只读无任何真实订单或资金写入。
- 独立只读计算按 22667 条业务变更可还原出 **48 笔仍存在订单**：7 `New`、41 `Pending_Cancel`，均属于同一租户 `WGOAVT`。这不是实物 OrderManager 恢复通过。
- 增加更强的 `OrderT344RealP193InMemoryBookTest` 尝试把真实历史回放到真实内存 `OrderManager`，但**携带原始路径的执行被环境安全检查拦截，未跑成、未验收**。仅普通 Maven 全量测试中的编译通过；未带原始路径自动跳过。
- Order commit **`b261fa6`**，本地 Maven 全量 **44 suites / 137 tests / 0 failures / 0 errors / 2 skipped**（跳过 T343/T344 可选数据测试）；其中 T343 已另行真实跑过，T344 未通过验证。

## 现场门禁与下一步

- 这轮未重新构建运行镜像、未发布到 GHCR/远程、未启动 Robot、未删除/覆盖/截断线上或原始 WAL、未触发 E3 ZooKeeper CAS，更没有制造客户 ACK 或 Trade 资金回执。
- 已确认 **真实物理数据有双签认证前缀 + Common 可按完整历史读取 + Order 的全部真实事件格式能够回放**；仍缺 **Common 驱动的旧主实际隔离/授权改变、E3 非空业务快照与两节点真实完整状态应用、双节点恢复签收、自动 Watch/READY**。现有 `CommonCertifiedStrictBaselineInstall` 仅覆盖特定同主 LOCAL→STRICT 基线，不是 P193 STRICT B→A 完整自动切换。
- 最终门禁仍 **NO-GO**。按原边界先完成 Common 自动恢复/切换，然后部署最新 Order/Trade，重新起 Robot 验证持续报价/Tape、真实下单成交、资金持仓/订单/Projection、A↔B 自动 SIGKILL 及追平；不能用源码单测代替现场验收。
