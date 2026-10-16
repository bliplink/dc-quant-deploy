# Common 3.0.22 / com.app.dc 0.0.5 本地 ARM64 冷重建与 10 户真实交易验收（2026-10-16）

> 证据类型：**Mac mini 上真实本地 Maven/Docker 编译、真实容器启动、真实 SaaS 交易端到端验收**。本次**从未调用 GitHub Actions 编译**；Actions 的计费额度不足，在用户明确解除限制前禁止使用。**并未完成物理多节点 HA failover 或 200 tenants 负载验收**。以下日期均为 Mac 当前所在 Asia/Shanghai 时区。

## 1. GitHub 源码版本及本地一致构建

- `com.app.common` `saas-crypto` HEAD `e6f088034a8fe137bae9ae199eba276d331a5e90`，版本 `3.0.22-SNAPSHOT`，Mac Java8/Maven 离线全量 **300 tests / 0 failures**（早先旧工作树版本缺少 Trade recovery 类，已从最新 GitHub 重新检出，不能使用旧 Common 源码）。
- [`com.app.dc` PR #7](https://github.com/bliplink/com.app.dc/pull/7) 已合并 `dd08a2f7861d8930d5a26ff7b7dd951161eab0e1`，`0.0.5-SNAPSHOT` 唯一引用 Common `3.0.22-SNAPSHOT`，Connector/J `8.0.33`。
- [Order PR #19](https://github.com/bliplink/com.app.dc.ordersvr/pull/19) 已合并 `3a09170cb686b998d409b1214035498900ca3e1c`；默认关闭的真实 WAL+ZK Stat 签名源端接线已包含在这次 Order 本地编译中。
- 全量离线单元回归：**Common 300 / Order 387（3 skipped） / Trade 287 / MD 146，全部 0 failures, 0 errors**。
- 真实最终 JVM 容器库 SHA（Gateway、Order、Trade、MD 使用一致的 JAR）：
  - `com.app.common-3.0.22-SNAPSHOT.jar` SHA-256 `9ea938bf6f78d6f1acdf840dc539a4bca049872f96e3069fdb362f595574dd59`
  - `com.app.dc-0.0.5-SNAPSHOT.jar` SHA-256 `1a9fdd422dcf3b17a562ed331009db541833439d0bdeb9070ea9795c02ec759c`
  - 所有核心业务镜像使用 `mysql-connector-j-8.0.33.jar`，检查不存在旧 `mysql-connector-java:5.1.24`。
- 采用 Mac **`linux/arm64`** 构建、`--pull=false`，并用 Docker image label `dc.common.jar.sha256` 和 `dc.common.revision` 对应实际 JAR/hash 检查：
  - `dc-saas/gw:cluster-dev-ha322-local-20261016` image ID `sha256:c4fedeb47b60c66062d3b20e6a27bde39a386b32384bb5d7240de6a0997741d1`
  - `dc-saas/ordersvr:cluster-dev-ha322-local-20261016` image ID `sha256:3e01c73db0af900dfd883952733ad93c457396fe399ee603fad7103f7e46973a`
  - `dc-saas/tradesvr:cluster-dev-ha322-local-20261016` image ID `sha256:01bc913192f13574470d8e6423f4d38808806829251c44f2982630e06264a922`
  - `dc-saas/mdsvr:cluster-dev-ha322-local-20261016` image ID `sha256:a36f1e542b47fbef9bf36e8f8f60434d8ac2fdab13f4d73493d940e673811c07`
  - **Gateway 透传 Java 业务代码未变，仅更新已验证的共享依赖 JAR**；相关镜像不可变锁为 Mac 本地 `~/.opentradingcore/local-ha322-release-20261016/ha322-images.env`（不含密钥，不依赖在线 GHCR）。

## 2. 安全隔离旧 Demo、冷启动排障经过（不可遗漏失败记录）

**原因：** 09:32 原 Trade A/B 热升级后，实际分区 WAL 存在 `lastSeq=commitMarkerSeq+1` 的未提交尾部。Trade 的 fail-closed 安全门禁拒绝恢复为业务 READY，8 Robot 转 ERROR；回滚旧镜像无法移除该持久尾部。不可假称热切已通过。

- 使用项目已有官方 `scripts/mac-saas-reset.py --mode plan` 检查全部 **24 个 Compose 服务**、严格 runtime 根目录和独立 `P246` 原始归档证据 SHA-256 `41ccc17752734ed3731764de9c0ca4135452c7903e95dd47e6bf7db0ae79a707`。随后通过官方受控 `--mode stage --confirm STAGE_DISPOSABLE_DC_SAAS` 完成**真正冷隔离**，没有永久删除旧数据：
  - 原根 `~/.opentradingcore/dc-saas-runtime-ordered-20261015`
  - 完整 quarantine `~/.opentradingcore/.dc-saas-quarantine/dc-saas-runtime-ordered-20261015-20261016T014850Z`
  - 新空数据根 `~/.opentradingcore/dc-saas-runtime-ha322fresh-20261016`。
- 通过 Mac 本地 `deploy-saas-macos.sh --full-cluster --skip-pull` 使用**16 个已缓存应用镜像**及缓存基础镜像；没有 GitHub Actions，也没有下载新的业务镜像。初始化全新的 MySQL、ClickHouse、ZooKeeper，真正写入 Order、Trade、MD 各 256 个分区，并完成 53 个 MySQL 表、全部 24 服务和五个健康 Web 入口的启动。
- 这次一键启动第一次被原私有 `TRADE_CLUSTER_REPLICATION_REQUEST_TIMEOUT_MS=1000` 阻止；按生成器公开安全下限更新为 `3000`。另一次被镜像不可变标签门禁阻止；通过**重构建镜像加正确真实 JAR SHA 标签**解决，而非跳过门禁。
- Mac **旧本地 `deploy-saas.sh`** 强制 `set_env_value TRADE_CLUSTER_ROLLBACK_UNCOMMITTED_TAIL_ENABLED true`，导致 Trade JVM 在全新空 WAL 启动时主动拒绝。检查发现 GitHub 远程 `saas-crypto` **已经修正为 false**；因此只让本地工作树的对应一行、测试断言与 GitHub 已合并源码对齐，`tests/test-trade-cluster-config.sh PASS`。私有运行配置同样改为 `trade.cluster.recovery.rollbackUncommittedTail.enabled=false`。在已完成其余服务启动的空基线下，**显式受控重启 Trade-B 后 Trade-A**，均恢复 128 分区的实际 `TRADE_PARTITION_READY`。**一键脚本此前由于此错退出非零，不能谎称最初的一键命令退出0**；经修正的运行集群已通过独立验收。
- **没有开启不受信任的 WAL rollback**、没有修改 ZK READY 让未提交 Trade 尾部自动放行、没有强行删除一条 WAL、没有清除 P246 证据，也未改变 Gateway 透传逻辑。
- Mac 资源非重启调优：Robot Docker 配额 `0.75 CPU / 1GiB`（swap 上限 2GiB），ZooKeeper `0.75 CPU`，并写入**本地私有**环境配置，保留在当前运行中。用户在重新部署前应检查这些配额，避免默认 0.2/0.1 核退化。

## 3. 真实 10 户交易和独立只读验收

- 创建**10 个全新的 Demo 租户**，不是导入原库，也不是只模拟订单：`MS8CE8, ORN68I, V2SBO2, S9PHHX, OUNWRX, G4HWGY, MI5KJ1, NOZWIC, XXILGZ, H0EJRE`。每个租户通过真实 SaaS HTTP API `tests/run-auto-tenant-trading-e2e.py`：自动申请/批准 → Robot 自动入金报价 → 20+20 活动挂单（盘口各十档）→ 创建交易员、Demo 入金 1000 → BTCUSDT **真实开仓成交 0.0001**、MySQL 成交与多头持仓一致 → Reduce-only 平仓 → 持仓0、交易员无活动委托 → Robot 自动补回 40 挂单。**10/10 E2E PASS**。所有私有日志在 `~/.opentradingcore/local-ha322-release-20261016/`，不提交任何密码或 API Key。
- 独立只读 `tests/check-demo-tenants-readonly.py`：**`PASS_10_TENANT_SNAPSHOT`**，10/10 `TRIAL/ACTIVE`，10/10 Robot `RUNNING`，**10 × 40 = 400** 笔活动 Robot 挂单，每户买卖盘口各十档且无交叉。JSON `ten-tenants-full-readonly-audit.json`。
- 独立 `tests/check-projection-consistency-host.sh`：`PASS`，已扫描范围 `orphan_mutations_observed=0`（**non_transactional=true**，不可当成全库原子证明）；Trade 和 Order Projection **各10份 watermark**，均无 Tail mismatch，跨分区 event ID 冲突未发现。JSON `projection-orphans-10-tenants.json`。
- 10 户 `tests/check-tenant-ramp-readiness.py`：`gate=BASELINE_READY_ONLY`、`reasons=[]`、`tenantLocations=10`、`enabledRobotsUnhealthy=[]`、CPU PSI some avg10 **13.08%**、Robot 配额使用率 **7.61%**、Order-B 最近3秒 Full GC **0**。**nextRampAuthorized=false**，不能称 50/200 户负载授权或订单 TPS 成功，市场数据频率 `1.56667/s` **不是**权威下单 TPS。
- 在 10 户全部交易结束后再次运行 `tests/run-saas-acceptance.sh --quick --running` **PASS**：Order、Trade、MD 各 256/256 分配 READY，Trade **当前 Epoch 真实业务 READY 256/256 A=128 B=128**，24/24 容器 running，Gw TradeSvr/TDSvr online，MySQL/ClickHouse/ZK/Web healthy，核心交易服务 OOM 均为 0。Trade-B 受控修正重启 1 次，其余核心节点重启计数0。Mac 磁盘约 **84%**，剩余约 **70GiB**。

## 4. 严格未通过项、后续安全边界

**10 户新数据 Demo 业务已恢复、可以演示；但 HA 耐久性与物理容错并未通过。**
1. 对已运行、持续交易的 Trade A/B **不能再简单 `docker restart` /滚动升级**：每分区仅一份同步 Replica，旧数据留下了未提交 WAL 分叉尾；需要真实复制成员 Quorum 完整 HEAD/签名、接收端恢复事务、可信 WAL 归档封存和安全晋升证明。先修机制，不能靠 `rollbackUncommittedTail.enabled=true` 绕过。
2. Order 三副本仍在同一台 Mac mini（**非真实物理独立 quorum**）。MD 的 `Safety` 对旧主 fencing、候选 Image/Diff 应用证明仍未全部接线并验收。没有执行本轮真实 `SIGKILL` primary、角色逆转、故障后资产权威一致性验收。
3. WAL 定时 Snapshot/归档/安全删除、Trade 跨节点持仓、Projection 全量事务性权威对账、50/200 租户持续负载、2–3× burst 仍需单独验收。
4. GitHub Actions **持续禁止**直至用户明确恢复；源码交付使用 GitHub `saas-crypto` PR/合并，所有编译继续在 Mac 本地 ARM64。

