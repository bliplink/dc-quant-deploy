# Robot 账号命名调整：仅作用于新租户

日期：2026-10-20。用户要求：**老租户不处理，只让新注册租户使用新的机器人交易用户名。**

- 新租户的 Maker 账号用户名为 `market-maker`，用户显示名称 `Market Maker`。
- 新租户的 Tape 账号用户名为 `tape-trader`，用户显示名称 `Tape Trader`。
- 同一租户内两个账号仍是不同的真实 `user_id`，分别申请原有独立 API Key，保持原资金、仓位、风控、启动机制；未修改 Robot Key 类型。
- 旧租户账号、用户名、`user_id`、API Key、机器人关联**一律不修改**。为确保旧试用租户即使未来重试初始化任务也不会改变用户名，逻辑依据持久化 `dc_tenant_liquidity_bootstrap.create_time` 和本次发布切换时间区分新旧；**不是根据应用运行时当前时间，也不是根据机器人阶段**。

## 固定切换边界

首次正式 Demo 切换时间：`2026-10-20 22:15:48.031`（与数据库所在环境 Asia/Shanghai 时区一致），此时刻之前创建的 bootstrap 任务永久走旧命名；该时刻之后创建的任务走新命名。配置项 `TRIAL_LIQUIDITY_FRIENDLY_NAMES_CUTOVER` 在版本发布后必须保持不变，不要在每次重启时改成新的当前时间。由 `config/admin-robot-friendly-names-20261020.yaml` 固定。没有此环境变量时，程序保守地回退旧命名。

## 代码与发布

代码源：`bliplink/com.app.dc.adminsvr` 分支 `codex/robot-friendly-usernames-20261020`，提交 `ec1ff68`。Java 8 编译、`TrialLiquidityBootstrapWorkerTest` 九项单元测试通过。编译使用当前部署容器的 classpath，确认与现网接口兼容。

只替换 AdminSvr 原镜像中 `TrialLiquidityBootstrapWorker.class` 和内部 `Job.class`，其余运行时代码未替换；本地镜像 `local/dc-saas-adminsvr:robot-friendly-new-tenant-20261020`，SHA `sha256:98ddfde54c43d8533750cd629495a5bf2e09bfdc136c702491f9885489e39b33`。部署只重建 `dc-saas-adminsvr`；Order、Trade、MD、Common 未重建。Compose override 固定镜像与切换时间，避免误伤旧租户。

## 验证状态

已通过：源码/Java 8 编译、9 项 JUnit 测试、新旧日期边界验证、AdminSvr 新镜像运行及环境变量生效、老租户 `B36KVV` 和 `NFH2SK` 的旧用户名保持不变。数据库只读检查显示旧任务的 `create_time` 均早于切换时间。

**尚未通过的验收**：真实新租户创建、Maker/Tape 自动注册，以及用户列表显示最终名称。尝试通过 Playwright 创建新租户的调用被执行环境阻止，没有完成；不要把单元测试结论当作真实业务验收。待可操作的自动化环境恢复后，创建一个新 QA 租户，并验证其真实 `dc_users` 与后台用户页面显示 `market-maker` 和 `tape-trader`，且两者 `user_id` 不相同、权限与密钥正常，再记录验收结果。
