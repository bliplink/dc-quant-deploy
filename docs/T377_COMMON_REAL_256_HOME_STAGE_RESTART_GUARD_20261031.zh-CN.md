# T377｜Common 自动 Home 接线与 256 分区真实 ZooKeeper 部分回切门禁

日期：2026-10-31（Mac CST 运行跨入 11 月 1 日时，以实际日志时间为准）  
范围：**隔离 Demo+Common**；现网 Order/Trade、Gateway、Projection、Robot **完全不重启、不换镜像、不注入故障**。

## 修改与边界

- 基准：与业务 T143 Common JAR 完全匹配的源码 `908ca02`，隔离工作树 `.work/t374-demo-common-ha`。
- 前序提交 `5306c41`：整个 Common JVM 共享两个 Failover 控制调度线程，不再逐分区起线程；`bb19778`：认证的、全 Replica 的自动故障恢复启动入口。
- T377 在 `CommonCertifiedNodeRuntime.AutomaticReplicaRecoveryPlan` 增加**可选、私有、按值复制的原始 256 分区 Home 布局**。通过 `armAllAutomaticReplicaRecoveryWatches` 自动判断本节点是否为该 Replica 的原始 Home：
  - 是 Home：使用**已有** `armAutomaticPhysicalRecoveryWatchExact(..., originalHome)` → `CommonCertifiedFailoverWatch.stageHomeReturn` → 现有 Common 协作签名交接及 READY 证明。
  - 不是 Home：仍使用原有自动故障接管 Watch；**无第二组选主/恢复状态机**。
  - 256 个原始 Home 分区必须唯一、合法；同一节点的所有 Replica Watch 使用相同不可变 Home 布局。缺失、重复、越界、跨 Watch 冲突或部分启用，在激活任何新 Watch 前就失败。
  - 当前实现对完整 Home Return 只允许 **STRICT_QUORUM** 物理 ACK 的活节点协作；E2/E3 的 `LOCAL_DURABLE_ASYNC` 不能未经证明直接转为严格回切。最多一分区处于未完成的签名交接，不能靠脚本伪造 READY 来放行后续分区。
- 不修改 Order、Trade 业务处理、Gateway 发现/透传或报价业务；ZK 仍为冷控制面，不参与实际 WAL 写入/ACK 热路径。

## 隔离构建和严格本地回归

- 新候选文件：`.work/t374-demo-common-ha/target/t377-common-home-auto-wiring.jar`。
- SHA-256：`dabbd5feceb577394e64cc299354b7f2060a85d4399d4e12b14a9663da8c33a0`。
- 使用 `tests/run-t376-isolated-common-physical-rsa.py`，固定候选 JAR、兼容 SLF4J、隔离 A/B RSA 身份与**克隆**的 T293 签名 WAL 夹具（原始证据不覆盖）。
- 最终回归：`discovered=45 executed=45 assumption_skips=0 ignored=0 failures=0`；新增 Home 原始布局、A/B 128+128 归属、输入修改后的值固定、255/256 缺项、重复 P000、越界 P999、跨 Replica 布局冲突与半配置拒绝。
- T359 旧回归提供 128 分区**模拟** READY 的控制面时序，不能当成真实物理 128 分区回 Home 时间。

## 独立三节点 ZooKeeper 真实控制面测试

测试入口：`tests/run-t376-isolated-common-zk-stage.py --mode home256`，固定上方 T377 JAR 哈希。新建三节点 ZK Compose、隔离网络、独立测试数据目录/签名身份；**真正的旧主 B 在独立 JVM 中持有持续有效 EPHEMERAL lease**。A 另起独立 JVM。

流程：

1. 真实 ZK manifest 包含 256 个分区：原始 Home 是 A 的 P000–P127，B 的 P128–P255；前一轮故障后 B 暂时成为全部 256 分区 Primary（A 作为 Replica），全部为 STRICT_QUORUM READY 元数据。
2. A 启动后从原始 Home 布局对 P000 发起一次协作交接，在真正 ZooKeeper CAS 到 Epoch 3 RECOVERING，落盘 A 的 RSA 签名前序；B 独立 JVM 仍有有效会话。**P000 不路由，另外 255 分区 manifest 保持原样 READY。**
3. P000 的 signed READY/业务 WAL 物理交接尚未完成时，P001 再次提交 Home Stage 被拒绝（`in-flight limit 1`）。统计：Home target 128，Home READY 0，peer READY 127，RECOVERING 1，B 原来的 128 个 Home 元数据保持 READY。
4. **A 的第一个 JVM 退出**，在同一隔离 ZK 上新建 A JVM、新 ZK 会话，通过签名 Stage Ledger 成功恢复 P000 的 E3 RECOVERING；仍不伪造客户 READY、不会把 255 个无关分区改变或误报 128/128 已完成。
5. 测试旧 B JVM、ZK 容器全部停止。证据位于 `.work/t374-demo-common-ha/target/t376-isolated-zk/t377-home-control-85cbd3ed.log`。

成功标记：

- `T377_REAL_3ZK_256_HOME_FIRST_RSA_STAGE_PASS total=256 unchanged=255 recovering=1 oldBLease=LIVE nextHomeStage=DENIED signedStage=FSYNC nonRoutable=true`
- `T377_HOME_RSA_PREDECESSOR_NEW_A_SESSION_RESTORED=PASS total=256 recovering=1 oldBLease=LIVE otherShardsUnchanged=255 READY=false`
- `T377_256_HOME_PARTIAL_CENSUS_PASS target=128 homeReady=0 peerReady=127 recovering=1 originalBHomeReady=128 allHomeComplete=false`

**测试性质必须严格标注：这是 256 分区真实 ZooKeeper + RSA 持久化前序的单分区协作转移及 JVM 重启恢复；测试驱动直接调用 Common `stageHomeReturn`，不是证明 128 分区从运行中的通用启动 Watch 全自动完成转移。该场景没有 256 份真实 WAL、旧 B 物理逐分区退休证明、独立双方 Snapshot/WAL 安装与签名 READY，也没有实际客户端 ACK。**

## 下一阶段唯一剩余主门禁

1. 用 Demo+Common 在真实 256 分区启动流程里通过 `openAndStartWithCertifiedAutomaticRecovery` 加载全 Replica Watch 和正确 Home 映射，证明默认每节点 128 个原始 Home，正确的非 Home 故障 Watch 注册，控制面 CPU/ZK QPS 不能进入交易 WAL/ACK 热路径。
2. 原主 B 仍在线时，A 对 128 Home 分区**通过 Common Watch 自动**按序取得独立双方 fsync、真实旧 Epoch 退休签名、可信 Snapshot/WAL 恢复并**真实签名 STRICT READY**；记录开始时间、完成时间、每分区耗时、全体 128 完成总用时、P95/P99 与部分转移时的实际客户可写区间。任何漏分区、双主、重复写或签名不完整都 NO-GO。
3. 从真实 A/B 故障回切和多节点负载中核对全部 256 WAL/快照及 opaque 业务水位的一致性；旧 E2/E3 LOCAL_DURABLE ACK 不能被追认为 Quorum。
4. 只有 Demo+Common 完整真实物理验收通过后，才统一把同一 Common 包接入 Order/Trade 镜像进行滚动替换。**现有业务保持运行**。

结论：T377 256 分区真实控制面与第一个 Home 的签名 Stage+重启恢复 **PASS**；完整 128 Home 真实 READY/总时间与 256 物理数据一致性 **仍 NO-GO**。
