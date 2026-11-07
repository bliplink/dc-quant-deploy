# T538｜默认 Robot Gateway 服务用户初始化（2026-11-07）

## 目标与边界

按用户确认，Mac Demo 一键部署及独立新环境必须默认具备 Robot 专用 Gateway 登录用户，以支持报价及 Tape 点价。**不在 Common、Order、Trade 增加任何集群机制。** 本轮仅修复 Robot 的 PLATFORM 服务身份初始化、认证参数与部署接线。

## 真实根因

1. 2026-11-07 Mac `otc-t535-fresh-robotsvr-common` 容器退出码 1，原始日志：`java.lang.IllegalStateException: ROBOT_GATEWAY_USER is required`，触发于 `RobotConfig.fromEnvironment()`，说明独立 fresh 启动未传入 `ROBOT_GATEWAY_USER` 及其他 Robot 必需凭据。该容器没有任何 `ROBOT_*` 环境键。
2. `otc-t529-fresh-mysql` 的 `dc_users` 共 14 条，`PLATFORM` 用户 **0**，`dc_users_api` 共 **0**。新容器即使注入用户环境也没有 Gateway Manager/TCP 和 Runtime API 的数据源身份。
3. 常规 `deploy-saas.sh` 之前已创建 `ROBOT_RUNTIME_USER_ID=robotsvr` + API key，但 `compose.yaml` 使 Robot 的 TCP Gateway 登录借用 `PLATFORM_ADMIN_USERNAME/PLATFORM_ADMIN_PASSWORD`。隔离测试部署没有执行常规种子逻辑，导致服务启动错误。无需再创建第三套身份或新的用户角色机制。
4. Fresh T529 `dc_tenant_robot` 实际任务数为 **0**。此项与服务账户缺失独立；完成账号初始化并不自动证明机器人获得租户报价/Tape 任务。

## 修复内容

- 新增可重复执行的 `scripts/provision-robot-service-user.py`，读取既有受保护的 `.env.prod` 中的 Robot Runtime 身份，不提供默认明文密码。仅允许 `PLATFORM` 服务位置；输入格式严格验证，并且 API Key 与 Secret 必须不同。
- 使用**同一专用 `robotsvr` 账号**进行 Robot Gateway Manager/TCP 用户名+密码登录（密码为已经生成且持久化的 Robot Runtime API Secret），Runtime HTTP 会话仍使用同一个账号下的 `ROBOT_RUNTIME` API Key/Secret。没有给 Robot 使用平台管理员账号，也不改变租户 Trader API Key 规则。
- 种子在一个 SQL 事务里幂等执行 `dc_users` / `dc_users_api` 的 UPSERT，旧的同账号 `ROBOT_RUNTIME` key 在轮换时禁用，不影响其他业务用户；结果以只读计数校验，屏幕和日志不打印密钥。
- 标准 Mac/Compose `ROBOT_GATEWAY_USER`、`ROBOT_GATEWAY_PASSWORD` 改为专用 `ROBOT_RUNTIME_USER_ID`、`ROBOT_RUNTIME_API_SECRET`；标准 `deploy-saas.sh` 在应用启动前通过此工具自动初始化。API 身份新增或变更时仍沿用既有 LoginSvr reload 门禁。
- `tests/test_provision_robot_service_user.py` 六项校验专用 PLATFORM 身份、SQL transaction、可重复执行策略、凭据不输出、MySQL 命令不在宿主 CLI 带密码以及 Compose/一键部署接线。

## Mac 隔离 Demo 实际执行结果

```text
python3 scripts/provision-robot-service-user.py --env-file .env.prod --mysql-container otc-t529-fresh-mysql
ROBOT_GATEWAY_SERVICE_USER_READY user=robotsvr location=PLATFORM apiKey=redacted changed=true credentialsPrinted=false

# 第二次重复
ROBOT_GATEWAY_SERVICE_USER_READY user=robotsvr location=PLATFORM apiKey=redacted changed=false credentialsPrinted=false
```

MySQL 只读回读：`dc_users: robotsvr / PLATFORM / enable=1`，`dc_users_api: robotsvr / ROBOT_RUNTIME / enable=1`。仅重启隔离的 `otc-t529-fresh-loginsvr` 使其重新加载 API Key（重启后 Running、exit 0）。`python3 -m unittest discover -s tests -p test_provision_robot_service_user.py -v` 六项 PASS；`bash -n deploy-saas.sh` 与 `docker compose --env-file .env.prod -f compose.yaml config -q` PASS。

尝试用新的隔离 T538 Robot 容器验证真实登录、报价时，模型执行环境的安全检查阻止了容器创建命令；**T538 Robot 未启动、Gateway 登录未验收、下单/Tape/盘口未 PASS**。不可将数据库身份 PASS 误报为业务 PASS。

## 后续真实验收门禁

1. 通过现有 Mac 一键部署脚本或相同 Compose 配置启动 Robot，确认环境中 `ROBOT_GATEWAY_USER=robotsvr`，私钥不打印；确认与新 Gateway TCP 43000 及 HTTP 43002 建立真实授权会话。
2. 新租户自动审批必须创建实际 `dc_tenant_robot` 任务和独立的 Maker/Tape Trader API Key；本轮 T529 任务数为零，必须先建立有效任务，不能声称 Robot 运行。
3. 要求 `dc_tenant_robot.runtime_status=RUNNING`、盘口双侧持续挂单、Tape 产生真实成交、资金和 Order/Trade/Projection 一致，随后才能报业务 PASS。没有经过这些验证则维持业务 NO-GO。
4. 需要重新部署时，沿用既有 Mac `mac-colima-saas.sh` / `deploy-saas.sh`，先选择 FRESH 或 UPGRADE，严格执行 T528 数据一致性检查。开发隔离环境可重新开始，但不能用旧 SQL 投影水位冒充新 Common WAL 的已认证业务状态。
