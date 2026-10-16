# 2026-10-16 Trade PR34 直接 Demo 滚动验收、未提交 WAL 复现与冷重建恢复

> **执行策略（用户明确授权）：** 不使用另建隔离环境；全部在 Mac mini 的 dc-saas Demo 上做真实本地编译、部署、复制/HA 测试。Demo 测试数据损坏时通过正式脚本原子隔离后重新部署。**GitHub 只提交源码/证据，在用户另行通知前不得调用 GitHub Actions 构建。** 无生产交易数据可复用承诺。

## 一、真实滚动升级：发现跨节点提交缺口

代码：[`com.app.dc.tradesvr` PR #34](https://github.com/bliplink/com.app.dc.tradesvr/pull/34)，merge `1563ddb92941929e7d692e126f9a9bfe824bbdd5`。Mac 本地 Java8/Maven **292 tests, 0 failures/errors**；真实 ARM64 候选镜像 `dc-saas/tradesvr:pr34-graceful-drain-local-20261016`，ID `sha256:9bd502d80302f74907f0b79b602aee8b6729e030fe910ca38febacb5f3e44629`。

在原 10 户、400 挂单真实 Demo 上，不停 Robot 直接 `docker compose up --no-deps tradesvr-b` 首次替换 Trade-B：
- B 新镜像启动正常，分区恢复日志无 `TRADE_PARTITION_RECOVERY_FAILED`；但 Robot **9 ERROR/1 RUNNING**（后续 8 ERROR/2 RUNNING），并且还在运行的旧 Trade-A 已留下**8 个未提交 WAL 尾部分区**，实际主写业务不能全部恢复。
- 根本边界：B 是另外 128 个分区的**同步 Replica**。B 关闭时，A 仍在写入，`TradeStateCoordinator.record` 先写本地 `STATE_BATCH`，再等待复制 ACK；ACK 失败时**不能**伪造随后的 `STATE_COMMIT`，本地就持久留下 `lastSeq=commitMarkerSeq+1`。恢复器正确 fail-closed。**仅对 B 自身 Primary 业务优雅 Drain 不能防止 A 在 B 下线期间继续写入**。
- 直接 Demo 验证新 B 正常 SIGTERM：`docker stop --timeout 90 dc-saas-tradesvr-b`，日志
  `TRADE_GRACEFUL_DRAIN_COMMITTED node:TradeSvrB partitions:128 businessWritesFenced:true authorizesFailover:false`。
- 随后把 A 也替换为 PR34 镜像，确认没有错误地自动修复 A 的旧脏尾；再执行真实 SIGTERM 触发
  `TRADE_GRACEFUL_DRAIN_PARTITION_BLOCKED` / `TRADE_GRACEFUL_DRAIN_BLOCKED`。八个受阻分区 `P008,P028,P046,P068,P082,P138,P178,P244` 均只差一条 Commit Marker；P028 `lastSeq=19241`、`commitMarkerSeq=19240`。Drain 等全部分区锁后撤销本地 READY，**不删除/截断原始 WAL，不伪造提交、不重新授权财务 READY**。
- 结论：**PR34 正常 SIGTERM 的本地提交 Drain 已经真实通过“健康及脏尾”两类试验，但正在交易中的 Trade 双节点滚动升级仍不安全。** 需要 Common 统一的跨节点 maintenance/drain fence 和耐久 Quorum Commit/Receiver Ledger；安全条件未建立时不能声称自动主切通过。下一步不应再只改一个节点的本地 restore/READY 判断。

## 二、真实 Demo 坏数据处理：安全隔离后同场地冷重建

- 已通过官方 `scripts/mac-saas-reset.py --mode plan` 的 P246 原始证据 SHA、24 容器与唯一运行根校验；然后实际执行 `--mode stage --confirm STAGE_DISPOSABLE_DC_SAAS`。**旧 Demo 数据完整保存在** `~/.opentradingcore/.dc-saas-quarantine/dc-saas-runtime-ha322fresh-20261016-20261016T032816Z`，未永久删除。
- 用 Mac mini **本地缓存镜像**的不可变锁 `~/.opentradingcore/local-ha322-release-20261016/ha322-images-pr34.env`，执行官方 `deploy-saas-macos.sh --full-cluster --skip-pull`，**真实退出码 0**。新运行根 `~/.opentradingcore/dc-saas-runtime-pr34fresh-20261016`。新容器：Trade-A/B PR34，Order/MD/Gateway 统一 Common `3.0.22-SNAPSHOT` + `com.app.dc 0.0.5-SNAPSHOT`；Gateway 透传业务代码未修改，MySQL Connector/J 8.0.33。
- **24/24 容器运行、MySQL 53 表，Gateway TradeSvr/TDSvr online，Order/Trade 各 256/256 READY**。真实 Trade 本轮空基线 `TradeSvrA=128` + `TradeSvrB=128` 条 `TRADE_PARTITION_READY`，`TRADE_PARTITION_RECOVERY_FAILED=0`。五个 Web 入口健康；未跳过官方服务配置及安全门禁。
- 已再次创建**10 个全新真实试验租户**，不是导入旧数据：`N8VSPZ,NF8OAP,PT2THG,IZT9RG,EQKL0W,RHKJJY,UR8J7S,NTJMIN,JAEZYQ,NU0Q4T`。每户 `tests/run-auto-tenant-trading-e2e.py` 实际依次完成自动注册/审批 → Robot 40 挂单/双向十档盘口 → 交易员 Demo 入金 1000 → BTCUSDT 真实开仓成交 0.0001、MySQL execution/position 一致 → Reduce-only 平仓 → 持仓归零 → Robot 补回 20 买单+20 卖单。**10/10 E2E PASS**，证据保留在 Mac 的 `~/.opentradingcore/local-ha322-release-20261016/pr34-tenant-e2e-01..10.log`。
- 独立 read-only `tests/check-demo-tenants-readonly.py` **PASS_10_TENANT_SNAPSHOT**：**10/10 RUNNING，400 挂单**，每户买卖各 10 档。报告 `pr34-ten-tenants-readonly.json`。
- 独立 `tests/check-projection-consistency-host.sh` **PASS**：已扫描区间 orphan Mutations **0**，Trade/Order Projection 各 10 水位无尾部 mismatch，跨分区 event ID 冲突未发现；`non_transactional=true`，**不得称为事务性最终资产权威对账**。报告 `pr34-projection-audit.json`。
- 独立 `tests/run-saas-acceptance.sh --quick --running` **PASS**：当前 ZK epoch 下 Trade 256 READY（A128/B128），24/24 Running，MySQL/ClickHouse/ZK/Web/GW healthy；Trade-A/B 0 OOM、0 容器异常重启。独立 10 户 ramp gate **`BASELINE_READY_ONLY`**、`nextRampAuthorized=false`、`reasons=[]`，CPU PSI some avg10 **22.61%**，Robot CPU quota utilization **8.32%**，并非 50/200 户容量与 TPS 证明。
- Mac 磁盘使用约 **85%**、剩余 **66 GiB**（保留历史隔离数据与测试证据）。运行中的 Order/Trade 周期快照依旧没有通过自动归档/删除验收；不能误声称归档开启。

## 三、未通过的真实 HA 工作

1. Common 统一**跨节点维护与发布隔离**：关 B 前须让另一台承担 A Primary 的节点停止发起会造成半批 WAL 的新业务，并等已接纳的 WAL/ACK/Commit Marker 完整落盘（不可用容器停止“替代”协议）。
2. **复制失败后未提交 WAL 的安全恢复**：保留并验证原始分叉尾部/哈希、可信来源持久 HEAD、独立物理节点 Quorum 签名、Receiver 恢复事务及 Ledger，禁止直接补 Commit/删除尾部，最终资金/持仓/订单/成交/Projection 全权威对账。
3. Order/Trade/MD 真正的 Primary `SIGKILL`、热副本晋升、旧主 Fence、节点追平与 role reversal 尚未验收。单 Mac 多容器不是多物理主机 Quorum。
4. 后续 WAL 低频定时 Snapshot、安全保留/删除、50→200 租户稳态+Burst 仍未通过。**Demo 可重复重置，GitHub Actions 禁用，源码通过 GitHub，Mac ARM64 本地编译镜像。**
