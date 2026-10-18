# OpenTradingCore 产品 Demo / Trade HA 冻结交接｜2026-10-18

**结论与优先级**：已恢复产品 Demo 的租户自动审批、Robot 登录、自动流动性配置和双边报价。此阶段**暂停 HA 开发/故障注入**，先做产品功能。严禁把 Docker 容器 Up、页面 HTTP 200、Robot 的订单计数或用户页面的最近成交直接当成 HA、账户成交和最终账务一致性验收成功。

## 一、2026-10-18 17:25 CST 实机现状（已核对）

- 环境：Mac mini，`/Users/kong/dc-quant-deploy`，运行目录 `/Users/kong/.opentradingcore/dc-saas-runtime-clean-20261016`，统一 `saas-crypto` 目标。
- 主站 `https://opentradingcore.com`、交易终端 `https://trade.opentradingcore.com`：实测均 HTTP 200；用户在界面已看见盘口和最近成交。
- 新租户 `GW7XMI`：正式 `tenantApplication` 自动审批，`TRIAL`、`registration_enabled=1`、`trade_enabled=1`，`reviewer_id=AUTO_APPROVAL`，无需人工审核。
- 平台身份已通过正式部署函数初始化：PLATFORM 下 `platformadmin` 和 `robotsvr` 两个启用用户，1 个启用的 `ROBOT_RUNTIME` API Key。LoginSvr 已重启刷新认证缓存，Robot Runtime/Maker/Tape 的 API Key 登录返回 `NO_ERROR`。
- `GW7XMI` 的 BTCUSDT Maker/Tape 流动性任务 **`COMPLETE:DONE`**，`tape_enabled=1`、`tape_funding_confirmed=1`，且无需重放现金操作；Robot **`RUNNING`、`enabled=1`、`open_order_count=40`**。RobotSvr 日志持续打印 Buy/Sell Tape 点价指令，APSSvr 正常更新 BTCUSDT 行情。
- **账务查验仍有边界**：用户确认 UI 的盘口和“成交”可见；但 MySQL `dc_orders_execorders` 中 `location='GW7XMI'` 目前为 **0**。UI 最近成交可能来自实时 MD 市场行情，不能由此证明该租户账户的真实执行记录已被 Projection 落库。后续产品验收要区分市场逐笔、机器人模拟成交、真实账户执行与资金持仓。
- **运行镜像固定记录**（这是本机 Demo，不是宣称生产 HA 正式通过）：

| 服务 | 镜像标签 | 镜像 ID |
|---|---|---|
| Trade A/B | `local/dc-saas-tradesvr:trade438-carriedepoch-2a043ac-20261018` | `sha256:95fc10bf1378313f4de62112333403777938780b3f8413e94802f19e081b1b18` |
| Order | `dc-saas/ordersvr:cluster-dev-fenced-transport-20261016` | `sha256:fd7c42e0088c69d1602d5842fbf13e895f15ad78d24329c7affd9116704e95e7` |
| AdminSvr | `local/dc-saas-adminsvr:trial-verify-recovery-20261018` | `sha256:3b8fb7be4c7349b1e52ef2355cb7844f02cb64fb56e2bae05f9ee1caf01a5449` |
| RobotSvr | `dc-saas/robotsvr:cluster-dev-local-robot-tape-precision-1a4aaae-20261012` | `sha256:d63857a715fda9b3db722fa49b789104cb13316982ced3c3f82ea4b0fb02e6fb` |

## 二、GitHub 源码提交与未同步风险

- `bliplink/dc-quant-deploy` **`saas-crypto`**：已提交正式身份补全入口 `deploy-saas.sh --provision-identities-only`、`tests/test-provision-identities-only.sh`、注册→自动审批→流动性验收及前置检查，另有按版本维护的 `docs/TRADE_HA_PAUSED_PRODUCT_DEMO_BASELINE_20261018.zh-CN.md`。
- `bliplink/com.app.dc.adminsvr` **`saas-crypto@46698459`**：`FAILED:VERIFY` 仅健康检查低频自动恢复，禁止重复入金；AdminSvr Maven 全量 88 项，0 fail/error、1 skipped，已在上述 Demo 镜像实机验证自动 `COMPLETE:DONE`。
- `bliplink/com.app.common` **`fix/common-trade-ab-integrate-20261018@68e37d3`** 已在 GitHub；包含物理持久化 Replica Commit Receipt、Snapshot/WAL 恢复基础能力。
- `bliplink/com.app.dc.tradesvr` **GitHub `fix/trade-ab-integrate-20261018@dd6a4db`**：最新两个本地已提交 HA 改动 **`dcbf10c`、`2a043ac` 尚未推到远程**。它们在 Mac 本地 `/tmp/otc-trade-ab-merge-20261018`（`HEAD=2a043ac909169c4c7e81973674e77cbf7362e712`），改动为 `TradeRecoveryInstallGuard.java` 及 `TradeRecoveredNonzeroHandoffGuardTest.java`。**运行中的 Trade438 镜像引用本地 2a043ac，而不是 GitHub 分支的 dd6a4db**。这两次远程提交尝试受到执行安全检查拦截，不能宣称已同步，也不能绕过；后续启用 HA 前必须在获准的发布环境补齐、比对构建源码及镜像。
- 原 Mac `/Users/kong/dc-quant-deploy` 主工作树仍有与远程 `saas-crypto` 大幅分叉的旧改动及未跟踪诊断材料；不要直接 `push --force`、`reset --hard` 或覆盖最新业务配置。远程已含 `mysql/migrations/20261008_trial_liquidity_tape.sql`、Common 集群契约及 P090 HA pilot 清单；不必重复提交。Order 工作树 `.work/ordersvr` 仍有两处**尚未验证的回调诊断改动**，未并入发布版，需单独代码评审。
- **当前 Demo 所用 `local/*` 镜像还没有形成可从远程干净检出、统一构建的正式发布候选。** 产品稳定后应锁定完整镜像清单、Common 依赖版本、构建基底和 Git SHA，再决定正式发布流程。GitHub Actions 暂不使用，所有提交 `[skip ci]`。

## 三、HA 暂停原因（不视为已验收）

- 真实 SIGKILL Trade-A 后，256 分区曾自动由 B 接管，但旧 Epoch 健康行与新 Assignment 不一致；A 的跨 Epoch 恢复安装/签名物理 ACK 收敛失败，旧环境最后已查到只有 7/256 精确 Replica 健康。此数值是**历史故障现场**，不是当前干净 Demo 的健康计数。
- 发生过两个并行执行会话分别杀 A/B，导致双节点同时退出；不是成功的双向单节点验收。后续必须唯一部署操作者 + 故障注入独占锁。
- `Common` 通用 Snapshot/WAL/diff、独立签名、接收端已安装镜像审计及 ZK Quorum 证据应持续复用；Trade/Order 各自注入业务状态机，MD 恢复遵循自身适配器。不得为了 READY 伪造 ACK、跳过物理审计、手工更改健康证明；也不改 Gateway 透传机制。
- 尚未取得 Trade A→B / B→A 两个方向 **非零持续订单、Robot 挂价/点价、带持仓** 的可重复自动故障切换；还缺少无双主、无丢单/重复成交、恢复副本追平，以及资金、持仓、委托、成交、Projection watermark、Trade 状态的最终权威对账。Order/MD 完整 HA、50/200 租户及 burst 压测亦未验收。

## 四、恢复 HA 时的执行顺序

1. **先保留当前可用产品 Demo**，停止一切并行 HA 容器替换和 SIGKILL；先补齐 GitHub 中 Trade 两个缺失源码提交并在隔离检出核对 Common/Trade/Order/MD 引用的实际版本，重建统一镜像。
2. 用新租户及 Robot 非零下单验证当前 Epoch、完整物理 ACK、Replica 提交水位、无进行中恢复事务，**256/256 精确健康**后才能注入故障；优先单 pilot，再扩展 fleet。
3. 注入 **SIGKILL 当前 Trade Primary** → 自动晋升、继续业务 → 恢复旧节点追平、成为 Replica；交换角色再验证 B→A，不允许脚本代替自动主切。短暂中断可以接受，不允许双主/重复成交/丢失已提交状态。
4. 跑最终权威资金/持仓/委托/成交、Projection watermark 及 Tape/账户执行区分对账；再执行 10→50→200 租户持续负载、故障恢复和 burst。HA 没过前不要重新宣称“生产级多副本”验收完成。

## 五、恢复/清理与文档索引

- 旧数据保留在 `/Users/kong/.opentradingcore/dc-saas-runtime-clean-20261016/data-product-pre-reset-20261018-141302`，切勿将旧 WAL/快照混入现有 Demo。
- 之前的 Docker 清单、SQL 初始化和重建日志：`/Users/kong/.opentradingcore/product-baseline-reset-20261018/evidence/`。这些是**本地排障资料，不含可公开发布的完整审计报告**，切勿将原始日志内的 Token/API Key 直接推 GitHub。
- 历史详尽信息见 `docs/TRADE_HA_PAUSED_PRODUCT_DEMO_BASELINE_20261018.zh-CN.md`、`docs/COMMON_CLUSTER_REUSE_CONTRACT_20261017.zh-CN.md`、`docs/TRADE_P090_AUTOMATIC_REVERSAL_ACTIVATION.zh-CN.md`。
- 产品继续验收：真实交易页面可见盘口/逐笔 → 订单/执行数据库与实时数据逐项核对 → Admin/租户/手机端功能 → API Docs / Python SDK / Broker API。**保持 HA 冻结，除非另行要求恢复开发。**
