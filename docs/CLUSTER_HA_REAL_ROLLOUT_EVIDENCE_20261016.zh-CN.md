# 2026-10-16 Mac Demo 集群真实角色切换验收证据

> 本文遵循 [集群最终统一验收任务书](CLUSTER_HA_FINAL_ACCEPTANCE_MISSION_20261015.zh-CN.md)；只记录真实已执行的操作。日期采用 Mac 所在时区 Asia/Shanghai。全程未新增产品功能，也未依赖 GitHub Actions。

## 2026-10-16 06:17–06:39 Mac MD PR10 真实滚动部署验收（最新状态）

> **真实实施完成，不是计划。** 本次仅修复现有集群恢复相关代码、验收脚本与 Maven 构建依赖；不新增产品或 Broker API 功能。Mac 的 DNS 无法访问 Docker Hub，且 `git fetch` 连接 GitHub 失败，因此所有 Java 编译、Docker 镜像均在 Mac 本地完成；代码通过 GitHub 连接器提交 PR。

### 1. MD 已合并修复的构建与镜像

- MD 的 PR [#10](https://github.com/bliplink/com.app.dc.mdsvr/pull/10) 包含 **Order Image 必须实际应用到当前 MD Epoch 后才可 READY** 修复。Mac 采用本地干净 worktree `f68eeee`（从现网基线 `6cfb994` cherry-pick 同一修复），并核对 `MdPartitionRuntime.java`、`MDFacade.java`、`DepthBookFacade.java` 的 **Git blob SHA 均与 GitHub `saas-crypto` 完全一致**。
- Java 8 / 离线 Maven 3.9.11：**33 套测试、142 项，0 failure、0 error、0 skipped**。本地依赖指向 `com.app.dc 0.0.5-devcombined-20261015-SNAPSHOT` 和 `Common 3.0.21-devcombined-20261015-SNAPSHOT`。新镜像 Common JAR SHA=`8898812068751cc3ab3916bb7b55fe535c10a413ffef7e9be20436d6ac8ff154`，`com.app.dc` JAR SHA=`ca9017749ed1a2a218a300ca92f7f1b2b16c273d0adbbc58a37d59f639c625ae`，均与当前 Order/Trade/MD 的运行 JAR 一致；MySQL 驱动为 **8.0.33**。
- Maven POM 上游默认仍为 `com.app.dc 0.0.4-SNAPSHOT`；现已通过 MD PR [#11](https://github.com/bliplink/com.app.dc.mdsvr/pull/11) 添加可覆写 `-Dcom.app.dc.version=...`，不改变默认线上依赖，也不使临时版本硬编码进仓库。
- `eclipse-temurin:8-jre` 在 Mac Docker 里未缓存，Docker Hub DNS 不可用；使用**运行中 MD 镜像作为缓存的 Java8 基础层**，用已通过测试的 `target/classes` 和 `target/dependency` 全量替换相同目录后生成新镜像。这不是业务逻辑替换之外的新增代码：
  - 新镜像 tag：`dc-saas/mdsvr:pr10-applied-epoch-20261016`
  - **完整 Docker image ID：`sha256:20d655e57548f8f5315d172e6476c28268ed377bddf4cf17c55d89ff1726a7e1`**
  - 原 MD 全部三个节点为 `dc-saas/mdsvr:epoch-refresh-after-subscribe-20261015`、源修订 `6cfb994`；现 A/B/C 全部使用相同新镜像 ID。

### 2. 真实 Demo 三节点替换与业务验收

- 滚动顺序：**MD-C（256 Learner、0 Primary）→ MD-B（128 Primary）→ MD-A（128 Primary）**，每次只重建一个节点，Order/Trade 未替换，也未人为改动 ZK 分区。
- 第一次重建 MD-C 遇到部署配置缺陷：旧 `.env.prod` 的 `DEPLOY_ROOT=/data/dc-saas-runtime` 是 Linux 路径，Mac 上 bind mount 不存在，因此容器创建后启动失败。**已立即修复并恢复节点**：只为 Mac 这次 Compose 命令覆写 `DEPLOY_ROOT="$HOME/.opentradingcore/dc-saas-runtime-ordered-20261015"`；不覆盖含密钥的源 env 文件、不清除数据。以后 Mac 重新部署必须显式带上此路径。MD-C 后续完整启动，先前的安装失败不能被伪记为零故障。
- MD-C 重订阅 Order 后 8 个活跃 Robot 市场 Image **8/8 `MD_MARKET_READY role:LEARNER`**；MD-B 负责的 3 个活跃市场 **3/3 `role:PRIMARY`**；MD-A 负责的 5 个活跃市场 **5/5 `role:PRIMARY`**。
- 三个 MD 容器均运行、OOM=false、restartCount=0；ZooKeeper MD **256/256 READY**，Primary A=128 / B=128，C 仍为 Learner。
- 用真实 `MDSvr.queryPublicMarket` 查询 **8/8** 活跃 Robot 租户，全部买盘/卖盘分别 **10/10 档**。Robot **8/8 RUNNING，320 挂单，8/8 有效租约**；其他服务仍然正常运行。
- SaaS Quick Smoke 最初检测到历史 READY 双重计数：Trade P000/P020 曾 A→B→A，旧脚本只按分区收集全历史日志，虚报 A=128/B=130 overlap=2。已修复为**当前 ZooKeeper 分区 Primary+Epoch 与实际 READY 日志配对**，同 Epoch 双主仍阻断；修复已合并到 deploy PR [#68](https://github.com/bliplink/dc-quant-deploy/pull/68)。真实全量 `--quick --running` **PASS**，包括 23 个容器、256/256 Trade READY A/B 各 128、全部配置和服务健康。
- MD 只读 failover 门禁的旧 GHCR 镜像标签误报已修复，新增当前容器镜像完整 SHA-256 锁定并测试，deploy PR [#67](https://github.com/bliplink/dc-quant-deploy/pull/67) 已合并。

### 3. Projection 全范围一致性核对

本机执行 `tests/check-projection-consistency-host.sh`。最初使用 75 秒上限只扫描 800,000 条并返回 `PARTIAL_NOT_ATTESTED`，**未将此错误伪称 PASS**。之后维护窗口内以 `PROJECTION_ORPHAN_MAX_SECONDS=360`、`PROJECTION_ORPHAN_CHUNK_SIZE=20000` 完成固定上界全范围扫描：

- `scanned=1486020` Mutation，`pages=75`，`elapsedSeconds=206.667`
- `orphanMutations=0`、`decision=PASS_LIVE_RANGE_OBSERVATION_ONLY`
- Order watermark **9/9**、Trade watermark **9/9**，tail mismatch 0；跨分区 event_id 冲突未发现。
- 本机报告：`$HOME/.opentradingcore/cluster-evidence/projection-orphan-post-mdpr10-20261016.json`。**注意：`consistentTransaction=false`、`authoritativeAttestation=false`，此 PASS 是固定上界在线范围扫描，不等同于故障后的完整强一致快照。**

### 4. 仍未完成，下一轮必须接续的真实阻断

1. **MD Primary 自动 SIGKILL：BLOCKED。** 在新版镜像实际 Image ID 上再次运行 `scripts/check-md-failover-preflight.py --expected-image-id sha256:20d655e5...`，没有任何“未审查镜像”误报；但以下五项仍为真正 blocker：`ORDER_CURRENT_FULL_MARKET_IMAGE_PROOF_MISSING`、`MD_PROMOTION_FENCING_AND_CAS_CONTROLLER_NOT_CONFIGURED`、`MD_RECOVERING_TO_READY_EPOCH_PUBLICATION_FENCE_UNATTESTED`、`MD_PROMOTED_EPOCH_FULL_MARKET_IMAGE_NOT_ATTESTED`、`ROBOT_POST_FAILOVER_ORDER_RECONCILIATION_NOT_ATTESTED`。**新 Image-READY 修复已部署，但自动主切机制尚未完成**；不要绕过安全门禁停止 Primary。
2. **Trade 带真实持仓的自动故障接管：BLOCKED。** 已合并 deploy PR [#66](https://github.com/bliplink/dc-quant-deploy/pull/66) 的受控 A→B→A 合法交易员资金/持仓查询验收候选脚本，已同步到 Mac 独立测试文件并通过语法编译；本轮发起真实持仓业务运行请求被执行环境安全检查拦截，**没有实际新建测试租户、入金或切换 Trade Primary**，不能把源码合并当作测试通过。
3. **Order Primary SIGKILL 自动接管仍未做，**前序执行请求曾被环境安全检查拦截；已通过的仅是三副本在线受控主备切换/真实 GTC 订单存续。
4. **WAL 自动归档、安全删除、10→50→200 租户稳态与 burst 未验收通过。** 磁盘此时约 82% 使用率（约 81 GiB 可用），未删除 WAL/旧 Demo 数据。不要重复已通过的 Image 与挂单切换检查；修复上述 Primary 安全授权后继续故障注入、资金/持仓/委托/成交与 Projection 权威对账。


## 本轮真实执行且 PASS 的项目

| 项目 | 动作和证据 | 结论 |
| --- | --- | --- |
| **Trade P000：空分区** | 当前 Demo 上 Trade A→B→A，ZK CAS epoch 1→2→3；两次新主均完成 READY；Projection 前后 14 条水位不回退。 | **PASS：人工受控角色切换** |
| **Trade P020：活跃分区（H4676T）** | 有业务持仓；Trade A→B→A epoch 1→2→3；B 恢复 `committedStateSeq=27061`、`riskAccounts=2`；A 恢复 `committedStateSeq=27093`、`riskAccounts=2`；两次新主均 READY，14 条 Projection 水位不回退。 | **PASS：人工受控角色切换与恢复门禁**，不等于“故障自动主切 + 客户持仓逐项校验” |
| **Order P000：三副本空分区** | A/B/C 同一快照，A→B→A CAS epoch 1→2→3；两次 `ORDER_PARTITION_PROMOTION_READY`；最终 A/B/C 快照 byte hash 一致。 | **PASS：人工受控角色切换** |
| **Order P228：活跃市场 H4676T** | A/B/C 三份已提交市场 Snapshot 完全一致，A→B→A CAS epoch 1→2→3；两次新主均 READY；实际 `MDSvr.queryPublicMarket` 双侧 **10/10 档**；最终三副本快照哈希重新一致。 | **PASS：活跃业务分区角色切换及行情服务** |
| **Projection / Robot 后验** | 全部切换后孤儿 Mutation=0，Order+Trade watermark mismatch=0，各 7/7；Robot 6/6 RUNNING、240 单，租约有效 6/6；八个 Order/Trade/MD 容器 0 重启/OOM。 | **PASS：所测项目** |
| **ZK 最终角色** | Order 256/256 READY，其中 P000/P228 epoch=3，另 254 分区 epoch=1；Trade 同样 256/256 READY，其中 P000/P020 epoch=3；MD 256/256 READY，仍 epoch=1。A/B Primary 各 128。 | **PASS：当前静态分配** |
| **MD-C Learner 真实 SIGKILL** | 上一轮实际终止并重启 MD-C，六个市场重新读取 Order Image，分区/Primary 未变化，原重启策略恢复。 | **PASS：Learner 故障恢复，不是 MD 主切** |

### Mac 上的原始证据

- Trade 空分区：`/Users/kong/.opentradingcore/cluster-evidence/20261016-001050-trade-role-reversal/summary.json`
- Trade 活跃持仓分区：`/Users/kong/.opentradingcore/cluster-evidence/20261016-001140-trade-role-reversal/summary.json`
- Order 三副本空分区：`/Users/kong/.opentradingcore/cluster-evidence/order-p000-role-reversal-20261015T161723Z.json`
- Order 活跃盘口：`/Users/kong/.opentradingcore/cluster-evidence/order-active-P228-A-B-A-20261015T161926Z.json`
- 最终 Projection：`tests/check-projection-consistency-host.sh` 在 2026-10-16 00:20 CST PASS；孤儿与双源 watermark 均无异常。

证据为本机受保护 Demo 文件，不是已上传公开仓库的日志/密钥副本。**角色切换操作采用在线版本 CAS；没有中断整个容器、触发自动选主或模拟物理节点故障。**

## 2026-10-16 00:26–00:28 Mac 新增真实业务回归：PASS

在以上 Order P000/P228、Trade P000/P020 在线角色切换全部完成后，执行：

```bash
set -a; . /Users/kong/dc-quant-deploy/.env.prod; set +a
python3 tests/run-auto-tenant-trading-e2e.py
```

- 新租户 **T1MPT1** 公开申请自动批准，流动性初始化完成，Robot `NOTIONAL_ZONES / RUNNING / 40`，公开盘口买/卖各 10 档。
- 新交易员正常注册登录、`Demo=1` 入金 1,000；真实 IOC 成交 0.0001 BTC，MySQL 订单/成交/Long 持仓吻合。
- Reduce-Only IOC 平仓完成；**测试交易员**最终持仓=0、活动订单=0，业务测试退出码 0。租户内的 Robot 做市账户仍可能有正常持仓，不能把“测试交易员归零”误写成“全租户全部头寸归零”。
- T1MPT1 测试后留在 `TRIAL`，Robot `RUNNING/40`；全 Demo 此时七个 Robot 运行，总目标挂单 **280**，七个租约仍有效。没有擅自删除测试租户。
- 后验 `tests/check-projection-consistency-host.sh` **PASS**：Order+Trade 水位分别 **8/8**，orphan mutation=0，watermark tail mismatch=0，cross-partition duplicated event ID=0。

**另外发现一个必须修复的验收工具问题：** `tests/run-order-live-role-reversal-e2e.py` 硬编码早期 `EX2ENF/P110` 隔离租户（当前 Demo 已不存在），并在 A↔B 变更时只更新 `replica` 单值、未正确更新同步副本列表 `replicas=[另一节点,OrderSvrC]`。因此**不能直接用于当前三副本集群**。现已用新脚本 `tests/run-order-three-replica-real-order-e2e.py` 替代该旧脚本并完成真实挂单穿越 A→B→A、正常撤单验收（详见新增 PASS 证据），旧脚本仍只适用其历史隔离拓扑，不应在三副本执行。

## 2026-10-16 00:34 Mac Order 真实 GTC 挂单存续验收：PASS

旧 `run-order-live-role-reversal-e2e.py` 仍绑定已经删除的 EX2ENF，并漏维护 Order-C，不能直接在三副本中用。**已编写、真实执行并通过的替代工具：** `tests/run-order-three-replica-real-order-e2e.py`（本 PR 同步提交源码）。

执行命令（需要 Mac Demo 合法的本地 env；不在日志显示任何密码）：

```bash
set -a; . /Users/kong/dc-quant-deploy/.env.prod; set +a
python3 tests/run-order-three-replica-real-order-e2e.py
```

- 通过 Manager 公开租户申请注册 **QE0L6W**，其 `BTCUSDT/4` Order 分区为 **P112**；等待自动审批、Robot RUNNING/40、三副本已提交市场快照 SHA 一致。
- 注册正常交易员、登录并 Demo 入金，真实提交一笔 **GTC 限价挂单**，`OrderSvr.queryOpenOrder` 可查。
- ZK 对 **单分区** 做带版本 CAS：**OrderSvrA→OrderSvrB，Epoch 1→2**，保留 A/C 两同步副本；B 经过 `ORDER_PARTITION_PROMOTION_READY` 后，以实际交易员 Token 再次查到同一个已确认订单。
- 再做 **OrderSvrB→OrderSvrA，Epoch 2→3**，保留 B/C 两同步副本；A 新 Epoch READY 后仍可查到同一订单。
- 真实 `cancelAllOrder` 后，该 GTC 不再在活动订单中；脚本退出码 0，输出 **PASS**，ZK 最终 **P112 READY / Primary A / Replica B,C / Epoch 3**。
- 实际本机证据：`/Users/kong/.opentradingcore/cluster-evidence/order-3rep-live-gtc-20261015T163433Zc30a.json`。测试租户留在 Demo TRIAL 持续 Robot 报价，为后续多租户压测提供样本；没有执行容器 SIGKILL。

**验收语义：PASS 是客户订单在双向主备角色切换中的存续与正常撤单，尚不是节点 SIGKILL 自动接管或带 Trade 持仓的资金权威对账。** 不要因本项通过误把全部 HA 目标完成。

## 尚未通过的关键项目与明确下一动作

1. **Order Primary SIGKILL 自动接管：BLOCKED。** 本轮尝试发起真实 Order-A SIGKILL 验收，但外部执行环境安全检查拦截了命令，**未终止节点、未修改 ZK**。不要谎称已做。后续通过合规可执行的故障注入途径，保留旧主隔离与已提交 WAL 验证，再做全链路自动接管和恢复节点追平。
2. **Trade Primary SIGKILL + 持仓账本：BLOCKED。** P020 人工主备切换已成功，现有 MySQL 持仓记录中有 2 个非零头寸；但接管到 Trade-B 的窗口内尚未以客户合法会话读取并比对实际资金、持仓及成交。平台 Manager 会话调用 `TradeSvr.queryTradePosition` 按权限返回 `1003`，不能以跨租户管理员请求绕过。需创建合法隔离测试交易员，持仓穿越故障、对账再平仓。
3. **Trade 恢复统计核查：仍须注意。** Trade-B 在流式 WAL 恢复时日志显示 `locations:0, riskAccounts:2`；`TradeRecoveryPlan.streamed()` 的 `getLocations()` 只来自零基线快照，而 `TradeRecoveryApplier.validateStreamed()` 会扫描 WAL 收集并恢复租户，因此 **`locations:0` 是计划统计不足，不能直接视为资金丢失，亦不能用 riskAccounts:2 代替精确账本对比**。最小修复只应解决验收证据或真实状态问题，不扩大功能。
4. **MD Primary SIGKILL 自动选主：BLOCKED。** 必须验证旧发布者 Epoch 隔离、接收端已应用的 Order 完整 Image + Diff、ZK CAS，不能用 MD-C Learner 恢复冒充主切。
5. **WAL 自动归档与安全清理、200 租户稳态及 2–3 倍 burst：未验收。** 要在故障接管/一致性先过门禁后继续；无证明不得删除正在被读取的 WAL。

## 接续顺序（切忌重复）

- **下一项：Trade 合法测试交易员持仓状态穿越接管的业务级核对，然后真实故障场景。** 确保复制 ACK 的已提交 HEAD、候选接收已应用内容，以及 READY 后 API 资金/持仓相等。
- 再执行 **Order-A 容器故障自动 promotion + 节点回归为 Replica**，核对 Order/Projection/Trade 全部资金订单成交，业务不中断或恢复窗口可量化。
- **MD Primary 自动故障接管**，再做归档与 10→50→200 租户压力。修复明确失败项 → 本地编译 → 替换 Demo → 只重跑必要的相关验收。
- 按用户授权，无法快速回退时可受控清理隔离 Demo 数据、重新部署并重新注册租户；不要绕过可信 WAL/旧主隔离门禁。

以上是本轮**验收记录**，不是全量 HA 已发布通过的声明。
