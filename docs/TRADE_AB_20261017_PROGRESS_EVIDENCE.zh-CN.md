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
