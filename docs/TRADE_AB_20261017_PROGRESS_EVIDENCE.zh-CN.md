# Trade A/B 双向自动恢复与主切验收记录｜2026-10-17 10:10 CST

> **本次验收状态：BLOCKED。** 仅代码测试与本机候选镜像构建通过；不代表 Demo 已部署最新版或 HA 已验收通过。不得脚本伪造 ZK 健康 ACK、READY、Epoch、物理 Replica 或恢复授权，不得在健康门禁未满足时进行真实 Primary SIGKILL。

## 已完成（有证据）

- Trade `bliplink/com.app.dc.tradesvr`：原修复 `0607f3a15a3b05ba73a66b36dfb93ddba9c4a721`（replication-health ZooKeeper version CAS、Epoch fence、health ACK 不回退）；源代码比旧 `saas-crypto=ca1cdd7` 超前 35 个提交，42 个变动文件。
- 已以保持相同源码树的整合提交 `a6916cf1426e5d6668600c5e8e9444bb995eefd9` 快进 Trade `saas-crypto`，提交带 `[skip ci]`，核对 Actions workflow runs=0。未使用 GitHub Actions。
- 在 Mac ARM64 上从独立干净 Trade 工作树 `0607f3a`，使用本机 Maven 3.9.16、Java 8 执行 `mvn -B -o test`：370 tests / 0 failures / 0 errors / 0 skips / BUILD SUCCESS；日志 `/tmp/trade-ha-20261017-mvn.log`。
- 本地 `mvn -B -o package dependency:copy-dependencies -DskipTests -DoutputDirectory=target/dependency` PASS；Common 3.0.22-SNAPSHOT SHA256 `6b4bf7aff300e69198587d06e7243c5c9594977b94b82f789f943f370bba12bd`，mysql-connector-j 8.0.33（未回退 5.x）。
- 新本地候选镜像 `local/dc-saas-tradesvr:ab-certified-0607f3a-20261017`（ARM64 image `sha256:3463c2cd7712932eff407e4d44140bf2e965ea7b1014485e540d966fc9fc35b0`），`dc.release.authorized=false`。**尚未部署**，不得把候选镜像当成 Demo 运行版本。

## Mac Demo 10:00 左右只读观察

- 运行实例：Trade-A `dc-saas/tradesvr:full-src-auto-fenced-fleet-20261017`，Trade-B `dc-saas/tradesvr:full-src-genesis-admission2-20261017`；源码/镜像未统一，均 restart=0/OOM=false。
- 真实 ZK：`127.0.0.1:32181`，`/dc/cluster/tradesvr/partitions` 共 256 个分区，现存 Primary 128/128；`/dc/cluster/tradesvr/controller/replication-health` children=`[]`，健康证明 0/256。
- Snapshot 全量枚举（仅快照元数据，不证明 WAL 是否完整）：Trade-A 256，偶数128个 epoch=1，奇数128个 epoch=2；Trade-B 256，偶数128个 epoch=1，奇数128个 epoch=3；当前奇数是 B Primary epoch=3，所以 **A 的 128 个奇数副本 Snapshot 尚未追平**。
- 两节点 periodic Snapshot、failover、replication.required 等开启，**但 A/B 的 `recovery.replica.autoWarm.enabled=false`**；B `recovery.replica.electedBootstrap.enabled=false` / `fleetEnabled=false`；A 还保持用于旧批次主切的 `genesisObserver.transferEnabled=true`，并不等价于双向副本健康同步。
- 本机日志：B 先前约 1732 条 `TRADE_RECOVERY_INSTALL_INCOMPLETE P001`（历史计数，未证实当前仍持续）；A 先前成功发出奇数分区 Genesis handoff CAS，并不说明 A 的回头追平已完成。
- Certified recipient physical evidence：B 的 `data/TradeSvrB/certified-recipient` 有暂存 `VERIFIED_STAGING_NOT_READY` 文件；A 的对应目录未发现。
- Mac 可用磁盘约 280GiB，ZooKeeper/MySQL 运行中且 Docker 显示健康。

## 接下来唯一优先事项（Trade A/B）

1. **真实完成 B→A 奇数分区的自动追平**：按 Common 完整当前 Epoch 源 HEAD / Snapshot / 原始 WAL、独立签名、ZooKeeper 版本 fencing、接收端原有 WAL 封存、恢复安装和独立物理安装证明；当前配置和接收端缺失的机制要修正，不能把 staging 的 `NOT_READY` 改名当通过。A→B 同样验证非空 WAL 情形。
2. 在两个物理方向真实健康后，补齐 `replication-health` 256 条实际匹配 Epoch、角色、持久 ACK 的证明（不伪造）；确认 READY/水位/业务审计闭环。
3. 依据安全滚动替换门禁在 Demo 部署**同一份已测试源码和 Common Jar**的 A/B 镜像；在发布流程中更正 OCI source revision labels，不能混淆基础镜像旧的标签。
4. **真实持续成交/持仓**条件下分别 SIGKILL Trade A、Trade B，观察自动 promotion 和节点自恢复为 Replica（**不得用脚本替代自动主切**）；验收无双主、无重复/丢失已确认提交，与 Order / Projection / MySQL 资金持仓对账。测试失败就做最小机制修复、本地构建与再部署；用户已授权 Demo 数据必要时重置。

本轮未修改现网 Trade A/B 容器、ZK READY/ACK/assignment、业务数据；未执行真实 SIGKILL。

## 本次会话新增实证｜2026-10-17

- Trade 源码安全修复已提交 `bliplink/com.app.dc.tradesvr@015acdaab960f2cff2a666edfad5fe80e668516b`：降级（`degraded=true`）时保留 ZooKeeper 同一 Epoch 的历史最高已认证 ACK 水位，恢复健康时拒绝低于该水位的 ACK，合法更高新 Epoch 独立建立基线。重新本地 `mvn -B -o clean test`：**371/371 PASS**，0 fail/error/skip。
- 双向签名恢复只读探针正式提交：`b5ec87edee2a7985f31e3194bc90518b3c9d3fe6`；A 的真实 HEAD 使用 RSA，而 B 当前真实 HEAD 使用 HMAC。探针之前错误地用 HMAC 检查 A，返回 `recovery proof/key algorithm mismatch`；已修复为根据真实签名算法选择 RSA/HMAC，并更新至 `18b1fc7f63be90b2450f484ea22c01c13464e2b5`。修复后两方向探针编译通过，Trade 371 项全量回归再次 PASS。
- **真实 B→A / P001 / Epoch 3**：直接接触 Demo 当前 ZK `127.0.0.1:32181` 与 Trade-B `127.0.0.1:19222`；`REAL_ZK_ELECTED_BOOTSTRAP_AUTHORIZED_NOT_INSTALLED` 和 `REAL_ZK_AUTHORITY_STALE_VERSION_REJECTED` 都通过，证明当前 elected source 身份与 source signed HEAD 匹配，伪造过期 ZK 版本被拒绝。
- **真实 B→A / P001 / Epoch 3 Snapshot+Manifest+WAL 窗口**：外部非运行态暂存目录 `/tmp/trade-ha-20261017-b-to-a-p001` 验证 `REAL_SIGNED_SOURCE_TO_REPLICA_AUDIT_SNAPSHOTS_READY_NOT_INSTALLED=1 rejected=0 epoch=3 walSlots=0 source=TradeSvrB replica=TradeSvrA`。确切范围是单个零业务 WAL 的分区，未写 A 的 live Ledger、READY 或 ACK。
- **真实 A→B / P000 / Epoch 1**：用 RSA 签名方式验证，返回 `REAL_ZK_ELECTED_BOOTSTRAP_AUTHORIZED_NOT_INSTALLED` 与 `REAL_ZK_AUTHORITY_STALE_VERSION_REJECTED`；这不是跨 Epoch 接收端安装或切换。
- 安全限制：向现网双向恢复配置写入密钥相关内容、以及执行 B→A 128 分区批量暂存验证，均被执行环境安全检查拦截。**未绕过阻断**，没有更改现网两节点配置、ZooKeeper 状态或交易数据；亦没有把失败/受阻验收计为 PASS。
- **未完成**：A 落后 B 的 128 份 Epoch 3 Snapshot 安装、真正独立签名 Replica 安装回执、256/256 健康记录、双向自动 SIGKILL、重启追平、真实资金/持仓/Projection 权威对账。与上节 BLOCKED 结论一致。候选 Trade 镜像尚未替换 Demo。

## 最新本地候选与最终现场复核（2026-10-17）

- **两方向当前 elected source 的实机只读证明**：B→A `P001/epoch3`（现网 B 的 HMAC HEAD）PASS；A→B `P000/epoch1`（现网 A 的 RSA HEAD）PASS；两个测试均明确拒绝伪造过期的 ZK assignment version。切勿把 `AUTHORIZED_NOT_INSTALLED` 误认为接收端完成恢复。
- 仅 `P001` 的 B→A 签名 Manifest/Image/WAL=0 外部暂存 `1/1` PASS；**128 个分区批量暂存触发执行环境安全拦截，没有通过**。
- 最新 Trade `saas-crypto` 探针修复提交 `18b1fc7f63be90b2450f484ea22c01c13464e2b5`；源码业务修复提交 `015acdaab960f2cff2a666edfad5fe80e668516b`。
- Mac 离线构建 371 tests PASS 的 ARM64 镜像 `local/dc-saas-tradesvr:ab-ack-floor-015acda-20261017`，镜像 SHA `sha256:7f2354fa9f6f95b47d19bf2bf08f633492d405038c5bd3d7ba479b29c77a7be2`；Common JAR SHA `6b4bf7aff300e69198587d06e7243c5c9594977b94b82f789f943f370bba12bd`、MySQL Connector/J 8.0.33，`dc.release.authorized=false`。**未部署到 A/B。**
- 最新只读现网观察：Trade-A 仍为 `full-src-auto-fenced-fleet-20261017`、Trade-B 仍为 `full-src-genesis-admission2-20261017`；ZooKeeper 复制健康证明 **0/256**；Mac 空闲空间约 279 GiB。**不得执行真实主节点 SIGKILL**，直到物理副本证明与认证接收端水位真正满足。

## 后续同日修复：存活 Primary 本地提交前先发布 DEGRADED（2026-10-17 10:45 CST）

- **严重故障门禁修复** `bliplink/com.app.dc.tradesvr@c8bf6c27235914daab2255135d43ab26bd2a6bc2`：原 `TradeStateCoordinator.maybeEnterSurvivingPrimaryDegraded` 能在 Replica 离线后进入本地持久化模式，却没有在 FIRST local-only STATE_BATCH 之前将当前健康证明以 ZK CAS 持久降级。旧健康 ACK 可能被恢复的过期副本用于提升，威胁 Primary 在降级期间确认过的资金/持仓。现在先重新读取当前 ZK assignment、核对 Epoch/角色/本地持久 WAL 与 committed marker，再持久发布 `degraded=true` 的**负提升证明**并回读；确认 ZK version/身份/副本仍离线/未产生新 WAL 后才允许单节点继续提交。ZK 写失败时不允许任何 unprotected STATE_BATCH。
- 加入单测 `TradeSurvivorNegativePromotionFenceTest`，覆盖降级状态匹配、不同 Epoch/Primary/Replica/dirty WAL/恢复副本的拒绝；扩展 `TradeGracefulShutdownDrainTest` 的真实 Chronicle 测试，模拟 ZK 拒绝 DEGRADED 写入，确认 WAL=0 且 committed watermark=0。修改已有假 ZK stub，使其模拟实际持久化并回读。Mac Java8 / Maven 3.9.16 全量 `mvn -B -o clean test` **374 tests / 0 fail / 0 error / 0 skipped / BUILD SUCCESS**。
- ARM64 离线构建新候选 `local/dc-saas-tradesvr:ab-survivor-fence-c8bf6c2-20261017`，镜像 `sha256:43c112458c518e4ecbc4cd840e8b7fe31b3cf30bb2ff9fe2dce086c661fcf0ef`；Common `3.0.22-SNAPSHOT` JAR `6b4bf7aff300e69198587d06e7243c5c9594977b94b82f789f943f370bba12bd`；MySQL Connector/J `8.0.33`。该镜像 `dc.release.authorized=false`，**未部署运行态**。
- 再次只读复查：Demo Trade A/B 依旧保持不同旧镜像，`autoWarm.enabled=false`（A/B）、B `electedBootstrap.enabled=false`，ZK `replication-health` 返回 `[]`（**0/256**），Mac 剩余 279 GiB。未执行任何真实 Primary SIGKILL；不存在 256 个物理健康副本的证据，不能认定双向 HA 通过。
- 本轮没有通过其他途径重试此前被执行环境安全检查拦截的现网密钥配置写入或 128 分区批量恢复验证，没有变更 ZK ACK/READY/assignment 或清理生产态数据。**Trade 自动副本追平→真实签名安装与业务财务对账→健康证明→双向 SIGKILL 的闭环依旧 BLOCKED，必须严格保持失败状态，不可伪造 PASS。**

## 2026-10-17 11:00 CST 新一轮推进（真实 ACK→ZK HEALTHY→自动重试）

**提交已合入** `bliplink/com.app.dc.tradesvr@6a0d3aa415b7a83c3d2b59ca93b1267118490344`（`saas-crypto`，`[skip ci]`，Actions 0）。发现 `TradeStateCoordinator.repairDegradedReplicaOnce` 原本在拿到 Replica ACK 后，就先清除本地 `degradedRepairTargets`、`failoverDegradedPartitions`、`survivorLocalOnlyPartitions`、`degradedPartitions`，再以 `strict=false` 写 ZK HEALTHY。一旦 ZooKeeper 写入失败，旧代码仅记日志，进而丢失自动重试目标，可能造成本地“已恢复”而 ZK 仍 DEGRADED。修复为：真实有序持久复制 ACK → 在分区锁内校验最新物理序号与仍合法的 Primary、Replica、Epoch、ZK assignment version → **ZK CAS 发布 HEALTHY → 回读验证真实 ACK 值和身份** → 只有成功才清除本地降级状态与重试目标。任何失败保存自动重试状态。Common/Trade 中断保护与 ACK 水位单调约束继续有效。

**验证**：`TradeGracefulShutdownDrainTest.recoveredReplicaAckCannotClearDegradedUntilZkHealthyCasIsDurable` 使用真实 Chronicle 持久 WAL：Replica 离线进入已认证降级；Replica 返回，耐久 ACK 成功但模拟 ZK healthy CAS 拒绝，继续保持 DEGRADED/重试目标；恢复 CAS 后二次 ACK 和回读成功，才恢复健康。现有 `TradeStateCoordinatorRecoveryGateTest` 补真实“Replica 已返回 ZK”必要条件。完整 Mac `mvn -B -o clean test` **375 项通过，0 失败、0 错误、0 跳过**。

**本地 ARM64 候选**：`local/dc-saas-tradesvr:ab-repair-ack-healthy-375-20261017`，Docker image ID `sha256:262ab41ecd0092b00111fce46b70ce64774c70d34a26a53448a1f3a476a21da1`；Common 3.0.22-SNAPSHOT SHA256 `6b4bf7aff300e69198587d06e7243c5c9594977b94b82f789f943f370bba12bd`；`dc.release.authorized=false`、**未替换 Demo**。

**现网只读证据（本轮）**：
- B `data/TradeSvrB/certified-recipient/P*/install/ledger/*.recovery` 的 128 个奇数分区记录均包含 `REPLAY_COMPLETE`；此处是 B 侧的 Common 持久安装状态，并不代表 A 已追平 B。纠正过去“B 无恢复 Ledger”的错误概括。
- A `data/TradeSvrA/certified-recipient` 目录不存在（没有 B→A 认证安装）。A 奇数分区仍 E2、B 奇数分区 E3。A/B `autoWarm.enabled=false`；B `electedBootstrap.enabled=false`，B `genesisReceipt.enabled=true`。A 缺 B 当前 SOURCE 恢复所需的对称配置/验签身份；B 当前 Source HEAD 为 HMAC，A 尚未配置其受信验签材料。不能擅自复制私钥或伪造 B 的物理证明。
- 真实 Netty+ZooKeeper `B→A P001 Epoch3` HEAD 签名及旧 ZK-version 拒绝再次 PASS，返回 `REAL_ZK_ELECTED_BOOTSTRAP_AUTHORIZED_NOT_INSTALLED`，**仅恢复源认证，不是 A 端安装或 ACK。**
- ZK `/dc/cluster/tradesvr/controller/replication-health` 仍 `[]`（0/256）。无法安全宣称双向 SIGKILL、追平与财务对账已通过。上次配置密钥写入和批量验证的执行环境安全拦截未绕过；在真实双副本水位认证前，没有执行主节点 SIGKILL。

**剩余关键闭环**：使 A 从当前 B-primary 的真正签名数据自动安装 E3 Snapshot/Committed WAL→Common Ledger REPLAY_COMPLETE→独立 A 物理回执与业务数据验收→B 真实健康发布（128 分区）；再对 A-primary 的128分区验证对称 Replica 当前水位/健康证明，完成 256/256；真实 A/B 双向故障和恢复自动切换、资产/持仓/委托/成交/Projection watermark 对账。严禁通过写一个任意 ZK healthy=0，或脚本手动切换来假装通过。

## Demo Trade A/B 直接清空重建 + 双向真实 SIGKILL 验收｜2026-10-17 11:18–11:36 CST

**已实际重建和部署**（不只本地打包）：
- 原始 Mac Demo 根目录 `/Users/kong/.opentradingcore/dc-saas-runtime-clean-20261016`。两个 Trade 进程和 Robot/Liq 在重建期间暂停，Order/MD/MySQL/ZooKeeper 没有重启；仅将 `data/TradeSvrA`、`data/TradeSvrB` 归档到 `/Users/kong/.opentradingcore/trade-ab-fresh-20261017-evidence/`，并重置 Trade 专属 ZooKeeper 命名空间 `/dc/cluster/tradesvr`，**未重置** `/dc/cluster/ordersvr`、`/dc/cluster/mdsvr`。
- 使用原有 `tests/trade_cluster_bootstrap_host.py --apply --confirm-root /dc/cluster/tradesvr/partitions`：每次 fresh bootstrap 的 `256/256` assignments `verify_exact PASS`，128 primary A、128 primary B，互为 Replica，`epoch=1`，`protocolVersion=3`。此为正常新集群初始分配，不是手工切换故障时的角色。
- A 端旧的 `genesisObserver.transferEnabled` 与 `fleetEnabled` 在 Demo 的现有配置中设置为 `false`，避免新建 Epoch1 时仍按旧零 Genesis 主动搬迁128奇数分区造成不必要 E2/E3 分叉；该操作未改变密钥。
- 实际 `docker compose up -d --no-deps --force-recreate tradesvr tradesvr-b` 使用同一新增 overlay `/Users/kong/.opentradingcore/ha-trade-ab-fresh-375-compose-20261017.yaml`，两容器均使用 `local/dc-saas-tradesvr:ab-repair-ack-healthy-375-20261017`，Docker image ID 同为 `sha256:262ab41ecd0092b00111fce46b70ce64774c70d34a26a53448a1f3a476a21da1`；实机容器内部 Common 3.0.22-SNAPSHOT SHA `6b4bf7aff300e69198587d06e7243c5c9594977b94b82f789f943f370bba12bd`，TradeStateCoordinator.class SHA `3b49eb6cefa3c4e2bc0215ef97cb03ba2ac7f283f555aa0d301b36c27dad791d` 完全相同。源码提交 `bliplink/com.app.dc.tradesvr@6a0d3aa415b7a83c3d2b59ca93b1267118490344`，375 测试通过、没有 GitHub Actions。
- ZK+Netty 真实只读复核：fresh Epoch1 `P090` A→B、`P180` B→A 的独立签名 HEAD 和 stale ZK version 拒绝均 PASS；这只证明恢复源身份和权限，并**非已完成副本安装**。

**真实 Docker SIGKILL，不使用任何人工 ZK 手动切换脚本**（两个独立空业务初始基线）：
1. `docker update --restart=no dc-saas-tradesvr` + `docker kill --signal=SIGKILL dc-saas-tradesvr`，实测退出码137，A ZK membership 消失，B 无 OOM/重启；B 自身 `TradeFailoverController` 自动 CAS 提升所有原 A-primary `P000..P127`，`128/128` 已记录 `TRADE_FAILOVER_PROMOTED`，Epoch1→2，`128/128` 进入 `TRADE_PARTITION_READY`。保留真实 ZK / 物理日志证据 `trade-A-SIGKILL-B-auto-takeover-evidence.json`。
2. 启动 A 且恢复 `unless-stopped` 后，A 的128个原主分区作为返回副本仍是 Epoch1，B 是 E2；A `autoWarm.enabled=false`、没有 Common 接收端安装 Ledger，**128/128 rejoin 未通过**；健康 ZK `0/256`。无数据/资金写入。
3. 为独立反向故障测试，再次只重置 Trade 空基线（另存两个节点数据，未伪造角色切换）；`docker update --restart=no dc-saas-tradesvr-b` + `docker kill --signal=SIGKILL dc-saas-tradesvr-b`，实测退出码137。Trade-A 原生 `TradeFailoverController` 将 `P128..P255` **128/128** 自动提升 Epoch1→2，且 **128/128 Epoch2 READY**；A 没有重启、没有 OOM。证据 `trade-B-SIGKILL-A-auto-takeover-evidence.json`。
4. B 返回且恢复 `unless-stopped` 后，也没有追平至 Epoch2，B 保持旧 E1 Snapshot，**反向 rejoin 未通过**，ZK健康 `0/256`。
5. **结束状态**：将空 Demo Trade 数据和 Trade ZK 进行第三次正式初始化，留下正常的均衡 128/128、**全部 Epoch1**，两边各256 Snapshot且各128主分区 READY。A/B、Robot、Liq 已全部重启；Docker restart policy均为`unless-stopped`。保留所有两次故障现场旧目录和 JSON 证据。最终 ZK health目录仍 `[]`（0/256），**不能称为完整 HA 已验收通过**。

**严格限定的安全范围**：本次 MySQL `dc_tenant`、余额、持仓、委托、成交记录均为 **0**；没有真实业务持仓、资金/委托/WAL 可用于零丢单测试。两次 A/B 接管都是 **空业务 Genesis Epoch1** 的授权特例，不等价于真实订单 / 非零 WAL / 资金一致性验收。尝试自动创建受控测试租户并调用真实入金 API 的操作触发 OpenAI 执行环境安全检查，被拦截后没有绕过该检查，所以本轮没有伪造真实业务负载。

**剩余明确 BLOCKER（不是自动选主）**：为 Trade-A/Trade-B 对称接通真实签名恢复源，开启其 `TradeReplicaRecoveryStageWorker` 的 `autoWarm` + `electedBootstrap` 与 bounded fleet，恢复已认证 Snapshot/原始WAL/物理 installLedger，添加/验证返回节点跨 Epoch 业务 READY/独立物理健康回执，并取得256个真 ZK health 证据。前述密钥涉及的现网配置写入曾被安全检查拦截，不能回避独立物理签名与接收端授权。实现后再次执行**不清理数据**的 A→B→A、B→A→B 真正回归，以及非零资金/持仓/委托/成交/Projection watermark 对账。禁止在未追平旧副本时再次连杀双主。

## 后续复核：Trade 恢复链路未接通，Order A/B/C 静态一致性预验收｜2026-10-17

**Trade 当前 Demo**：仍是统一 ARM64 `local/dc-saas-tradesvr:ab-repair-ack-healthy-375-20261017`，A/B 正常运行、各有256份 Epoch1 Snapshot、各128 Primary，`/dc/cluster/tradesvr/controller/replication-health` 为空。A/B 的 `autoWarm.enabled=false`；这不是简单打开布尔开关能安全完成的。恢复架构已具备签名 HEAD、完整 Snapshot/原始 WAL staging、Common Ledger `REPLAY_COMPLETE_NOT_READY`，但缺乏最后独立物理签名/账务 Projection 对账后才能发布 READY/HEALTHY 的闭环。两方向零 WAL SIGKILL 128/128 接管通过仍不能替代这条证明。

**新增可执行验收门禁** `tests/trade_ab_auto_ha_preflight.py`，配套 `tests/test_trade_ab_auto_ha_preflight.py` 七项测试通过，提交 `facbf4227014128eb6800e1b12584318d162eaf9`，`[skip ci]`。脚本只输出布尔/预期节点/端口/缺失字段，**不输出任何密钥值、不写配置、不改 ZK**。现场输出两端均 **`full-auto-recovery-config=BLOCKED`**。A 缺自身 Replica 签名身份、B→A 验证信任、恢复源、autoWarm/elected 全量、Genesis receipt/Replica 健康 observer；B 缺独立 RSA Source signer、reader trust、autoWarm/elected 和健康 observer；严格生产链路要求显式双向受信物理身份，不能凭当前单向 demo HMAC 或一个 flag 误判认证通过。此前涉及真实私钥配置更改被执行环境安全检查拦截，不绕过。

**Order ABC 预检查**：使用真实当前 Mac 环境只读运行原项目 `tests/verify-order-cluster-state-host.sh`，包括 `ORDER_CLUSTER_VERIFY_LEARNERS=true` 的完整副本快照比对，均 **PASS**：256/256 ZK 分区 READY、全 Epoch1，OrderA/B 各128 Primary、OrderC 作为全部256分区 Replica，所有指派节点的 Snapshot 完全一致，没有 `SN` 可疑字段；OrderA/B/C/Gateway 进程正常，重启0、OOM false。业务网关被登录认证门禁挡住，因此未执行真实下单/撤单/成交或 SIGKILL。完整 Order HA 尚未通过，**Trade 修复后按同样的副本追平/Quorum/资产一致性标准注入故障**。

**本阶段结论**：Trade 的 *双向自动接管* 在空业务测试中通过；*故障返回节点的完整恢复、持仓资金对账、256个认证 ACK* 仍 BLOCKED。Order 当前仅静态前置条件通过，不能提前宣称真实 HA 验收完成。

## 2026-10-17 12:00 CST｜Trade Common 恢复后物理审计已补齐并替换 Demo，Order 静态预检通过

- **Trade 代码提交**：`bliplink/com.app.dc.tradesvr@2c3b97984cfb184292624249064d98867528dbf8`（`saas-crypto`、`[skip ci]`）。在 `TradeCertifiedRecoveryReceiver.recoverStagedCrossEpoch` 与 `recoverStagedElectedPrimaryBootstrap` 接收端恢复完成后增加 `TradeRecoveredPhysicalAudit.requireInstalledNotReady`，独立回读 Common `DurableRecoveryInstallLedger.REPLAY_COMPLETE`、当前物理 Snapshot Epoch/序号/原始哈希、Chronicle WAL Epoch/seq、源 HEAD 的 Snapshot/committed-state/commit-marker 完整边界。不匹配则 fail-closed；成功也 **仍为 NOT_READY**，不是独立物理副本 ACK 或账务/Projection 一致性证明。不能凭 Common ledger 单独发布 HEALTHY。
- **本地完整回归**：Java 8 离线 Maven `mvn -B -o clean test` **379/379 PASS、0 fail、0 skip**；新增4项异常物理后置检查（不完整 Ledger、过期 Epoch、脏 WAL、Snapshot哈希/业务摘要不匹配）。
- **实际 Demo 已替换镜像**：A/B 均使用 `local/dc-saas-tradesvr:ab-physical-postflight-379-20261017`；ARM64 image `sha256:887befd6da2d125c1b454cc004d3b09058710150944aea6d3de4dac0b1cb3673`，Common 3.0.22-SNAPSHOT SHA256 `6b4bf7aff300e69198587d06e7243c5c9594977b94b82f789f943f370bba12bd`。新 overlay `/Users/kong/.opentradingcore/ha-trade-ab-postflight-379-compose-20261017.yaml`，只重建 Trade 两容器，其它 Order/MD 未重启。ZooKeeper 256分区仍 A/B 各128，全部 Epoch1；两节点各256份初始 Snapshot Epoch1，A/B 无 OOM、无自动重启、最近运行日志无报错。此修改没有现网非零 Epoch 恢复路径验证。
- **实测自动恢复必要配置审计**：`tests/trade_ab_auto_ha_preflight.py` 的7项回归通过，当前现场 A/B 均 `BLOCKED`，细项见该脚本 stdout。A 缺 B→A 恢复来源信任/自身物理签名身份、autoWarm/electedBootstrap；B 缺单独 RSA 源端签名身份、双向健康 observer、autoWarm/electedBootstrap。此前涉及密钥配置更改操作遭执行环境安全检查拒绝，**不绕过/不伪造证据**。
- **Order 只读预检**：`tests/verify-order-cluster-state-host.sh`，含 `ORDER_CLUSTER_VERIFY_LEARNERS=true`，两个模式均 PASS。真实 Order A/B/C/Gateway 进程均在，A/B 128/128 Primary，C 为全部256分区副本，**256/256 Snapshot exact equal**、所有分区 READY、全部 Epoch1，0 OOM/重启。没有认证业务会话，故没做真实委托、SIGKILL、持仓与 Projection 对账。
- **当前正式验收**：空业务基线 A→B、B→A 独立 SIGKILL 各128/128自动接管PASS；恢复节点跨Epoch真实追平、可认证物理 ACK、256/256健康 ZK、非零真实订单资金一致性 **仍未通过**。严禁把379项测试通过或临时 READY 当完整Trade HA通过。

## 2026-10-17 13:06 CST｜新增非零 WAL 恢复后的真实物理 Replica 回执协议（已部署到 Demo，默认关闭）

**Trade 提交** `bliplink/com.app.dc.tradesvr@3f0fcb3de28c1c1b964731a7f6fcc4232ada61ee`（`saas-crypto`、`[skip ci]`）。之前的 Common `RecoveryInstalledGenesisReceipt` **强制零 WAL/零余额/零持仓**，无法认证非零业务恢复；这次新增 `TradeRecoveredReplicaReceipt` 协议 `TRADE_RECOVERED_REPLICA_PHYSICAL_RECEIPT_V2`：
- Source 发带新随机 challenge 的当前 Epoch、ZK 版本、Snapshot SHA / committed WAL watermark 的完整 RSA Source HEAD。Replica 的 `TradeRecoveredReplicaProofEndpoint` 在自己的分区业务锁里校验源签名、ZooKeeper 当前主备、旧 Epoch 原始封存及 Common `REPLAY_COMPLETE` Ledger、真实 Snapshot SHA 与 Chronicle 完整前缀，**先物理同步 Chronicle**，然后才用**本节点独立 RSA 私钥**签署包含 nonce、source/replica、ZK version 和所有准确恢复边界的回执。错误或未完成 Ledger 返回 `UNSAFE`，不改 READY、ZK 或业务状态。
- Source 新增 `TradeCertifiedRecoveredReplicaObserver`，只对已自动切至 `epoch>1` 的当前 Primary 分区，用自身业务锁、再发 RSA Source HEAD 和 Netty challenge，校验独立物理 Replica 签名、源端业务状态和 ZK epoch/version 未变化，才能以精确 seq 写 ZK replication-health 并回读；默认 `trade.cluster.recovery.replica.physicalHealth.enabled=false`，严格 1..8 分区每次扫描，切换仍由 Trade 内部故障控制器负责，不由脚本修改角色。
- 新物理回执接入 `TradeRecoverySourceHeadEndpoint` 的直连 Netty Control（Gateway 无改动），启动链路接入 `TradeStart`。两端需 `trade.cluster.recovery.replica.physicalReceipt.enabled=true`、独立 RSA Node 信任、autoWarm+elected 安装；没有这些条件**不自动宣称健康**。
- **单元测试**：新加 5 个用独立 2048bit RSA 生成的挑战回执测试，覆盖真实非零 WAL HEAD、签名篡改/伪造、重放 nonce、旧 ZK version、改动 committed WAL 边界、无效输入/默认关闭。Trade 离线 Maven `clean test` **384/384 PASS、0 failed/error/skipped**，其他原有 379 用例全部保留。
- **本地 ARM64 实际镜像** `local/dc-saas-tradesvr:ab-nonzero-physical-receipt-384-20261017`，image ID `sha256:cc2d076bd27276057c0d2528d6b36439eea7f75aaf35e49c1657f4c7a975a1d4`。已**实际替换**运行 Demo 的 `dc-saas-tradesvr` 与 `dc-saas-tradesvr-b`，两边确认同一 Common Jar SHA `6b4bf7aff300e69198587d06e7243c5c9594977b94b82f789f943f370bba12bd`、同一 `TradeRecoveredReplicaReceipt.class` SHA `70c3557597bb5d37c3261e9c7f1a96824057b30910217a3bd04574e5c64a502c`，A/B 正常运行、OOM false、restart0，256 ZK assignments 保持各128 Primary、全部 Epoch1，两个物理节点各256份 Snapshot，近期无启动错误。Compose overlay `/Users/kong/.opentradingcore/ha-trade-ab-receipt-384-compose-20261017.yaml`。Order/MD 未触碰。
- `dc-quant-deploy` 脚本 `tests/trade_ab_auto_ha_preflight.py` 已追加检查两端 `replica.physicalReceipt.enabled` 和 `replica.physicalHealth.enabled` 的独立配置；7/7 Python 测试通过。当前两端仍 `BLOCKED`，因为关键双向受信身份/签名配置、autoWarm+elected 安装和实际 ACK 未激活。这是实测而不是推测。
- **仍未通过最终验收**：此非零 receipt 已实测协议+Java单元测试、容器启动，但**没有完成真实 Mac B→A/A→B 跨 Epoch 的物理安装、独立业务/Projection 财务对账和 ZK 256/256 健康证书**。真实当前 ZK `replication-health=[]`。不可用此次提交掩盖真正 HA 仍待完成。此前敏感签名材料现场配置尝试被安全检查拦截，本轮没有尝试绕过。
- **Order** 仍保持既有只读静态 256/256 Snapshot 验证 PASS；按用户要求待 Trade 真正恢复并验收之后再注入真实 Order 故障，暂不同时使两个撮合核心失效。

## 2026-10-17 13:11 CST｜非零已提交快照的真实 Chronicle/Common Ledger→RSA 物理回执端到端验证

- Trade 新增 `src/test/java/com/app/dc/service/cluster/TradeRecoveredReplicaProofEndpointTest.java`，提交 `bliplink/com.app.dc.tradesvr@0dc477a3202fc5f1b3d14422452c3d7ad00a9f9f`（`[skip ci]`），不调用真实生产密钥。测试创建并封存老 Epoch1 Chronicle/Snapshot，然后经正式 `TradeRecoveryReplicaJournalBaseline.forCertifiedCrossEpoch` 安装 Source Epoch2 的 **`snapshotSeq=2 / committedStateSeq=1 / committedHeadSeq=2` 非零提交水位**，Common 持久 `DurableRecoveryInstallLedger.REPLAY_COMPLETE`，由被测真实 `TradeRecoveredReplicaProofEndpoint.handle` 验证签名 source HEAD、物理 ledger、Snapshot、CQ，并用独立 2048 位 RSA Replica 私钥签发回执，再由 Source publicKey 完整核验。回执本身不修改任何 ZK 或 READY。
- 3 项端到端检查 PASS：正常已安装的非零 Snapshot 提供可验 RSA 回执；错误旧 ZK version 和删除 Common Ledger 均拒绝；不合法追加的 Chronicle 尾部也拒绝。连同此前的 5 项 RSA 协议伪造/过期/重放检查，当前 Java Mac 离线 Maven `clean test` **387/387 PASS，零失败、零跳过**。
- 对已在 Demo 运行的 `ab-nonzero-physical-receipt-384-20261017` 二进制，再次使用真实 Netty+ZooKeeper `TradeLiveElectedPrimaryAuthorityProbe` 只读测试：`P090` A→B signed Source HEAD、过期 ZK-version 拒绝 PASS，`P180` B→A signed Source HEAD、过期 ZK-version 拒绝 PASS；实机输出均 `REAL_ZK_ELECTED_BOOTSTRAP_AUTHORIZED_NOT_INSTALLED`，**这不是已完成安装证明**。
- 只在测试源码新增新回归，Demo 现有 `384` 镜像仍包含相同生产代码，可继续运行；无需因新增测试而反复重建 A/B 生产镜像。下阶段最关键依然是对称独立节点凭证/接收端当前 Epoch 安装门禁的授权、autoWarm/electedBootstrap/签名 receipt 实际启动、256/256真实 ZK HEALTHY、带业务现金/持仓的双向 SIGKILL 后重新自动追平与账务 Projection 对账。此前执行环境安全拦截的密钥配置行为仍未重试或绕过，严格不提前宣称 HA 完成。

## 2026-10-17 13:24–13:28 CST｜修复两个真机制漏洞：慢 Replica ACK 不阻塞撮合 + 旧 Snapshot/非零 WAL Manifest 基线

**Trade 实际提交与部署**
- Commit `bliplink/com.app.dc.tradesvr@65e96e20aaafcced5893425512d17376c0536f52`：`TradeCertifiedRecoveredReplicaObserver` 不再在 Primary 的分区业务锁内等待远程 Netty RSA ACK（以前最长8秒，会阻塞正常业务）。新流程：锁内固定当前物理 Epoch/ZK version/完整 Source HEAD 与随机 nonce → **锁外远程 Replica 获取并验签** → 重加业务锁核对完整 HEAD/epoch/version/Replica liveness → 精确健康 ZK CAS+回读。新4项竞态用例对并发新提交、改变 Snapshot/state、Epoch 等全部拒绝。全量 **391/391 PASS**。已实际通过 ARM64 `local/dc-saas-tradesvr:ab-lock-free-physical-ack-391-20261017` 双节点替换 Demo。
- Commit `bliplink/com.app.dc.tradesvr@c9485ad08184804aaa0b99235b30762093bb2d46`：**真实自动恢复 bug 修复**。原 `TradeReplicaRecoveryStageWorker.stagePartitionOnce` 错把 signed Source HEAD 的**最新** `committedStateSeq/commitMarkerSeq` 填入 Snapshot **baseline**，当 `snapshotSeq<committedHeadSeq` 且后面还有真实 WAL 时会与 Common 的 Source signed Manifest 不一致，恢复无法继续。修复使用同一随机 challenge 另外读取/校验当前源端的 `RecoverySnapshotManifestAttestation`（真实签名、当前 ZK version、源节点、Snapshot SHA/epoch），然后从 manifest 读取 `baselineStateSeq/baselineStateEpoch/baselineMarkerSeq`，保留 Source HEAD 最新 committedState/commitMarker 作为 WAL 目标边界；Common staging再次独立验证新的 signed HEAD/Manifest。实现 `signedManifestRecoveryRequest` 并明确区分 Snapshot 基线和 WAL head。非零状态接收端也增加 Chronicle `TradeCommitWatermark.scan` 对 Snapshot 和最终 `STATE_COMMIT` 的物理水位校验。新增4项回归。Trade 全量 Java8 Maven **395/395 PASS、0 fail/error/skip**。
- ARM64 镜像 `local/dc-saas-tradesvr:ab-signed-manifest-wal-395-20261017`，image ID `sha256:b099f6f21a169df1c2a0a89067f01e94c98cec2f0ba22e4f786b7394c9668f2b`，已于本次会话**实际替换** Demo 两个 Trade 容器；版本一致，Common Jar SHA256 `6b4bf7aff300e69198587d06e7243c5c9594977b94b82f789f943f370bba12bd`、TradeReplicaRecoveryStageWorker.class SHA256 `7810e662585180c6182adbbf5381b7edb9304bd0ea60cccaeb08f21101beea10`。当前 256 分区均衡 A/B 各128 Primary、全部 Epoch1；两个节点各256个 Snapshot，OOM false、restart0、最近150行日志无 ERROR。Compose：`/Users/kong/.opentradingcore/ha-trade-ab-manifest-wal-395-compose-20261017.yaml`。Order/MD未改动。
- Commit `bliplink/com.app.dc.tradesvr@e38440a70fe1995ac1a85fae52d36fb4bf1ce94e`：强化只读实际 ZK + Netty Source probe，在核验 Source HEAD 后，**用同一 nonce 读取真正签名 Manifest**，用来源/版本签名比对 Snapshot baseline，打印源端快照和 WAL suffix 长度，不输出密钥、不写 ZK、不装业务数据。实际 Demo 运行：`P090 A→B` 与 `P180 B→A` 均 PASS：
  `epoch=1 snapshotSeq=0 baselineCommittedStateSeq=0 baselineCommitMarkerSeq=0 sourceCommittedHeadSeq=0 requiredWalSlots=0 imageBytes=334 NOT_INSTALLED`。两个方向过期版本拒绝 PASS。
- **本轮状态严谨限定**：`autoWarm` A/B 仍关闭（独立物理密钥配置先前受执行环境安全检查阻断）；ZK `replication-health=[]`、真实 ACK **0/256**。本轮代码已解决运行时慢 ACK 锁阻塞和含非零 WAL 的错误 Snapshot baseline，但**尚未实机完成非零 WAL 跨 Epoch 恢复、完整持仓/资金/委托/成交/Projection 财务对账，更未通过256真健康证明**。不能将 395 单测、签名 Manifest、空业务下 A/B 128/128 自动接管等同完整 HA。

## 2026-10-17｜Trade A/B 又修复零 Snapshot + 新 Epoch 第一笔已提交 WAL 的真实恢复阻塞

**实质性源码修复**：`bliplink/com.app.dc.tradesvr@d2bf2c33655711bca9e59130ca6cf32a64e40765`，`saas-crypto`，`[skip ci]`。
- Source 端 `TradeRecoverySnapshotManifestSource.requireSourceManifest` 以前凡 `snapshotSeq=0` 就强制 `committedHeadSeq=0`，导致刚升任 Primary 并开始交易、定时 Snapshot 尚未生成时无法签发真实 Snapshot Manifest。修复：仍要求 Snapshot **确实完全 Genesis 空态**，源 WAL 无提交时维持零状态；若源真实提交则要求最新 HEAD 为当前 Epoch 完整的 `STATE_BATCH/STATE_COMMIT`（`sourceCommittedStateSeq>0`、`sourceStateEpoch=currentEpoch`、`commitMarkerSeq=committedHeadSeq>=2`）；零高度 Snapshot 的 Manifest baseline 永远保留 `0/0/0`，绝不把源最新业务状态混入空 Snapshot。
- Receiver `TradeCertifiedRecoveryReceiver.requireStagingMatchesOldEpoch` 的静态判据亦曾把 `snapshotSeq=0` 硬绑定 `committedHeadSeq=0`。同步改为只有旧 Epoch 原始 WAL / Snapshot 基线确实为空、当前新 Epoch 完整提交语义可验证时允许真实非零 WAL 追平；仍拒绝旧 Epoch 脏尾、跨节点伪造、不完整提交、来源 HEAD 与ZK版本不符。Common 原始 WAL 验签/持久化、旧证据封存、独立节点签名认证和财务对账门槛均未绕过。
- 新增/更新三组测试：`TradeIdleSourceManifestTest` 两项：Genesis Snapshot 后已提交 WAL 的真实 Manifest PASS，不完整 WAL 拒绝；`TradeCrossEpochReplicaTailSealTest` 一项：旧空 Epoch + 当前 Epoch 第一对 STATE/COMMIT 合法、脏旧尾及不完整 HEAD 拒绝；`TradeGenesisWalSignedTransportTest` 一项 **真实 Netty loopback 端到端**：Source Epoch2 空 Snapshot、真实 Chronicle 写入原始两条 STATE_BATCH/STATE_COMMIT、签名 HEAD + Manifest，Replica 通过 Common `VerifiedRecoveryStagingClient.stageWithSourceManifest` 认证下载全部 Snapshot/WAL、逐帧校验独立源身份/原始日志字节、序号/Epoch/业务事件及预期提交标记。测试完全隔离，不修改真实 Demo 的 ZooKeeper、账户或业务数据。
- 当前 Trade **Java8 Maven full `clean test` 399/399 PASS、0 failures/errors/skips**。
- 新 ARM64 镜像 `local/dc-saas-tradesvr:ab-genesis-plus-wal-399-20261017`，image ID `sha256:a450dfb1599dbab4bca9d01818898ee8a9c133d56903ec6e155a2fdbfd5966b9`，已双节点实际替换 Demo；相同 Common 3.0.22-SNAPSHOT jar SHA `6b4bf7aff300e69198587d06e7243c5c9594977b94b82f789f943f370bba12bd`，同一新版 Source Manifest Class SHA `6cba17431f7dc10fbdd77402e33b624df9494b8fd04b5c2f0fd14888e7bc7ac1`。运行状态：A/B 全部在线、OOM false、restart0、近期无 ERROR；ZK Trade 全部 256 READY、Primary A/B 各128、Epoch1；双方各256 Snapshot；Order A/B/C未重启，Order 256分区同样 READY（A/B各128）；磁盘余量 276 GiB。Compose overlay `/Users/kong/.opentradingcore/ha-trade-ab-genesis-wal-399-compose-20261017.yaml`。
- **关键未验收真实指标保持不变**：A/B `autoWarm.enabled=false`，ZooKeeper `replication-health=[]` / 0/256 真 ACK。这里的真实 Netty 验证是**隔离测试中的认证传输和暂存，并非生产跨物理节点自动安装成功**；非零交易/资金/持仓/Projection 最终对账也没做。依然需要两节点受信恢复签名身份、自动安装启用、后置认证完整物理 ACK 和业务财务对账才能连续双向真实 SIGKILL 通过。此前修改实际恢复密钥配置被执行环境安全检查拒绝，没有尝试绕过。
