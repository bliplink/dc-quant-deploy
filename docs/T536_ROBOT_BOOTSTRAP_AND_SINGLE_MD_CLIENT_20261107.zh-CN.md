# T536｜Robot 自动初始化接线预检与共享 MD 客户端单机路由修复（2026-11-07）

> **状态：已交付源码、构建候选镜像、自动部署防回归；现网 Robot/Tape 仍 NO-GO，自动 HA 仍 NO-GO。** 仅认真实测试/运行证据，不将单元测试等同业务成交，不宣称后台继续执行。

## 1. T535 真实业务前置基线（未改动原业务数据）

T535 的全新隔离租户 `RU7WZO`、`J4BMAH` 使用 Broker 自定义测试价格 `90001`，经授权 Gateway→APS→MD，两个交易员各入金 1,000 USDT，Maker/Taker 两个真实订单 Filled、两条非零执行，Trade 资金与 Long/Short 持仓均经真实接口读回。Order 256 分区 + Trade 256 分区共 512 对 E2 原始 WAL SHA A/B 一致。**这不证明严格 ACK、自动故障切换、真实 Binance 实时价格或 Robot/Tape。**

T536 查询运行中的 `otc-t535-fresh-gateway-upstream`、`otc-t535-fresh-apssvr-custom`、`otc-t529-fresh-adminsvr`、`otc-t529-fresh-managersvr`、`otc-t532-fresh-mdsvr` 均 running，业务未重建，测试数据未清除。当前 Order/Trade 的 `automaticRecovery=false`，没有做 SIGKILL。

## 2. Robot/Tape 自动初始化真实阻塞（根因有代码和数据证据）

新 MySQL 的 `dc_tenant_liquidity_bootstrap` 有 **6 条 `PENDING/CREATE_MAKER`**；`dc_tenant_robot` **0 条**。这些申请属于本轮已自动审批的测试租户；并非没有生成任务。6 条任务 `tape_enabled=0` 是流程初始状态，真正处理到 `REVOKE_CASH` 时才根据当时启用的参数决定是否进入 `CREATE_TAPE`，不能据此声称 Tape 已运行。

`TrialLiquidityBootstrapWorker.poll()` 第一个门禁是环境变量 `TRIAL_LIQUIDITY_BOOTSTRAP_ENABLED=true`；Maker/Tape 密码通过 `TRIAL_LIQUIDITY_MASTER_KEY` 长期稳定派生，必须至少 32 字符。T531/T535 **当前全新环境 .env** 原本已有一把 48 字符、与旧环境分离的稳定初始化密钥，且配置文件中有 `TRIAL_LIQUIDITY_BOOTSTRAP_ENABLED=true` 和 Tape 参数；但**实际 T529 Admin 容器没有将它们加载进环境**，导致 worker 什么都不执行。因此不能凭 .env 文件存在就报“Robot 自动启动”。

T535 诊断用 Robot 候选 `otc-t535-fresh-robotsvr-common` 已将其内置 Common 3.0.16 替换为相同验证代际的 Common 只读挂载，但缺 `ROBOT_GATEWAY_USER`，实际 **exit 1**；启动前还需要同代际正式 Gateway 账号以及独立 Robot Runtime API Key/Secret。绝不能复用旧部署密码或将空字段当有效认证。

使用新增**只读、零凭据输出**预检验证**实际容器**：

```bash
python3 tests/check-trial-bootstrap-runtime.py \
  --admin-container otc-t529-fresh-adminsvr \
  --robot-container otc-t535-fresh-robotsvr-common
```

实测返回 **exit 2（预期的 NO-GO）**：`ADMIN_BOOTSTRAP_DISABLED`、`ADMIN_BOOTSTRAP_MASTER_KEY_ABSENT_OR_TOO_SHORT`，以及 Robot `ROBOT_GATEWAY_USER` / `ROBOT_GATEWAY_PASSWORD` / `ROBOT_RUNTIME_LOCATION` / `ROBOT_RUNTIME_USER_ID` / `ROBOT_RUNTIME_API_KEY` / `ROBOT_RUNTIME_API_SECRET` 缺失。工具只验证有效环境变量是否已真正注入，**不输出密码、不请求交易、不修改数据**。

直接携带平台登录和 Robot API Key 签名的实时检查被执行环境安全机制阻止，未执行。没有通过拆分命令、沿用旧凭据或直接修改 MySQL 绕过。**因此实际 Robot/RUNNING、持续深度报价、Tape 点价成交仍然 NO-GO。**

## 3. 正式 Compose/Admin Worker 修复（部署回归）

已提交修改 `compose.yaml`、`compose.trial-liquidity-local.yaml`、`deploy-saas.sh`：

- 正式 `adminsvr.environment` 现在明确传递 `TRIAL_LIQUIDITY_BOOTSTRAP_ENABLED`（缺省 **false**）、独立 `TRIAL_LIQUIDITY_MASTER_KEY`、Maker 资金参数、Tape 是否开启、灰度租户及 Tape 资金参数；不会因为装了 Worker 类就误称其已启用。
- `TRIAL_LIQUIDITY_DEMO_RETRY_ENABLED` 在 Compose 中强制 **false**。源码 `FUND_IN_FLIGHT` / `TAPE_FUND_IN_FLIGHT` 对账机制必须保留，资金返回不明确时严禁盲目重复入金。
- `deploy-saas.sh` 生成和持久保存**专用** `TRIAL_LIQUIDITY_MASTER_KEY`；不再复用 `DC_HEDGE_CREDENTIAL_MASTER_KEY`。部署升级要保持原有稳定密钥，不得重新随机生成后覆盖已存在的 Bootstrap 密钥，否则已创建的 Maker/Tape 用户无法按既定密码登录。
- 试用专用 Compose 覆盖 `compose.trial-liquidity-local.yaml` 是 opt-in，要求显式稳定主密钥，允许限定 Tape Canary。**生产默认不自动入金**；不能把演示权限自动打开到真实资金环境。

实测在独立的 `t536.env` 上，对正式 Compose 和 opt-in Compose 运行 **`docker compose config --format json`** 并通过只输出布尔结果的测试：Admin 8 个流动性相关配置键存在、密钥长度合格、Demo 自动重试为 false；试用覆盖模式为 true 时能显式开启。没有 `docker compose up`，**运行中旧 Admin 未切换**。

新增 `tests/check-trial-bootstrap-runtime.py` 和 `tests/test_check_trial_bootstrap_runtime.py`：**5/5 单元测试通过**；包含禁用 Worker、缺主密钥、危险自动重试、Robot 身份缺失及不安全 Docker 名称拒绝。

## 4. 共享 MDSvrClient 修复：Trade 读取单机 MD 时不能误查 Multi-MD 分区

T535 Gateway 的公开行情接口已经正确支持单机 MD，但 Trade 内部共享客户端 `com.app.dc.utils.MDSvrClient.mdPrimary()` 仍强制查 Common `PlacementRegistry/PartitionRegistry`，实际日志有 `MDSvr partition is not routable: Pxxx` 警告。

在 **`bliplink/com.app.dc:saas-crypto-latest` 远端最新版源码**上实现并提交：

- `MDSvrClient` 的 `@Value("${md.cluster.enabled:true}")` **默认严格多节点模式**。只有官方生成配置明确写 `md.cluster.enabled=false` 时，初始 MarkPrice Image 请求使用真实 `SERVER.MDSvr`，保留原 tenant+symbol 业务请求 key，不捏造分区或 Epoch。
- `md.cluster.enabled=true` 继续通过 Common 的分区 Placement→当前 READY 主节点路由，失效则拒绝，不能自动降级。
- 官方 `generate-saas-configs.sh` 对 `TradeSvr`、`TradeSvrA`、`TradeSvrB`、`LiqSvr` 同时从 `MD_CLUSTER_ENABLED` 生成 `md.cluster.enabled`。
- 部署预检 `tests/preflight_saas_cluster_config.py` 校验 Trade/Liq 客户端模式与 Gateway 模式同源且一致；缺少属性或模式不一致直接 NO-GO。

测试证据：在真实 T521 Trade Java8 镜像和同版本依赖下编译远端最新类，`MDSvrClientTest` **10/10 JUnit PASS**（新增单机 Image 以及默认 Multi-MD 严格模式）；部署预检 **10/10 Python 单元测试 PASS**，独立 T536 真实生成配置 + ZooKeeper 只读校验 PASS，生成的 4 个 Trade/Liq 目标全为 `md.cluster.enabled=false`。

已构建本地候选镜像：`local/otc-t536-tradesvr:md-single-mode-prepared`，镜像 SHA `340b9317f4ec72c3b97fa09b33e539cfff567356b01e04b626527d5624acdde2`。它仅覆盖共享客户端 class，不改 Common 集群 WAL/选主；**未替换运行中的 Trade A/B**。因为现网 `automaticRecovery=false`，直接重启可能不能自动追平，必须先保证可验证恢复/允许明确重置后再全链路回归。

## 5. 仍未通过的真实门禁与下一步

1. **Robot 初始化：NO-GO。** 当前真实 Admin/Robot 容器未收到正式凭据和开关；必须以本代际经授权的身份启动并验证 `CREATE_MAKER → CREATE_KEY → FUND → REVOKE_CASH → [CREATE_TAPE → CREATE_TAPE_KEY → FUND_TAPE → REVOKE_TAPE_CASH] → CREATE_ROBOT → ENABLE → VERIFY`。任何未知资金结果遵守原对账门禁，不得重复入金。
2. **Robot 价格源：NO-GO。** 目前代码默认 `APSSVR_BINANCE_TICKER`，T535 Mac 外部 Binance WS/HTTPS 真实网络不可达；自定义 Broker 价格通过 APS→MD 的 PASS **不等于 Robot 能拿到合法持续行情**，不得用静态假行情声称真实 Robot 深度持续报价。
3. **Order 真正批量撤单：NO-GO。** `OrderStateJournal.beginSynchronousBatch` 仍显式抛出 `ORDER_COMMON_DURABLE_BATCH_NOT_CONNECTED`，必须以 Common 已认证 WAL staged-before-apply 业务状态机接线解决；不删门禁、不先改订单再写日志。
4. **Trade A/B 自动 HA：NO-GO。** 此前订单/资金和 A/B WAL SHA 验证 PASS，但生产式自动恢复没有启用，不存在故障注入后自动主备互切、严格客户端 ACK、重新追平与双向无双主的端到端证明。

## 6. 交付引用

源码：`bliplink/com.app.dc:saas-crypto-latest`（`MDSvrClient.java` 与 `MDSvrClientTest.java`）；部署：`bliplink/dc-quant-deploy:saas-crypto-latest`（配置生成、预检、Compose、启动脚本和新 Runtime 预检）。继续严格遵守“先日志与可复现根因，再修改/部署；集群实现都在 Common、业务只使用 Common SPI”的约束。
