# T442｜新租户默认 100 倍杠杆：根因、修复与 Demo 实测（2026-11-02）

## 根因证据

- `com.app.dc.adminsvr/saas-crypto` 的 `TenantUserService.initializeTradingAccount` 在新开户 SQL 中硬编码 `dc_users_symbol_config.leverage=1`，同时影响普通交易员、Trial Maker、Tape。
- Trade `DataFacade.getSymbolLeverage` 没有账户配置时默认 100，但 `initSymbolLeverage` 加载数据库账户产品配置后，被新开户记录的 1 覆盖。
- Mac T398 MySQL 只读核对：JRHHXA 的 001100000001/002 与 KCV203 的 001200000001/002，BTCUSDT 产品杠杆均为 **1**。已有认证 WAL 持仓保证金与 1x 一致，解释 5000 资金不足的主要原因。
- Robot `depth_leverage=1` 是报价预算倍率，**不是 Trade 账户杠杆**，本轮没有扩大报价预算。

## 提交与构建

- AdminSvr 新建 `saas-crypto-latest`，源码 commit `c08dcb10d56cbf1d054570edfe14aca6bbb9e43e`：改用 `DEFAULT_TRADING_LEVERAGE=100` + JDBC 参数绑定。
- 测试 commit `fe2625d0b60e0b241a1003d16226a04237bebd51`：通过实际 `initializeTradingAccount` JDBC 代理验证写入 SQL、五个参数与 100 倍。
- Mac 原生 Maven 3.9.11 （官方压缩包 SHA-512 已校验）`mvn clean package`：**24 suites、102 tests、0 failures、0 errors、1 skipped**。
- 原 Dockerfile 基础镜像 `eclipse-temurin:8-jre` 未缓存且 Docker Hub DNS 不通；使用本机现有镜像 `local/otc-t406-adminsvr:safe-enum-category` 作为离线基础，仅覆盖编译后的 `TenantUserService.class`，产出 `local/otc-t442-adminsvr:100x-onboarding`。
- 20:03 左右创建并启动 `otc-t442-adminsvr-100x`（host 网络、旧容器共享挂载、继承全部环境配置）；12 秒后仍运行且建立 AdminSvr ZooKeeper 会话。旧 `otc-t406-adminsvr` 停止并保留，供回滚。

## 真实新租户验证

- 通过正式 Gateway `http://127.0.0.1:33002/httpapi/` 执行现有 `tests/verify-tenant-auto-approval.py`：提交、自动审批、状态查询、重复申请幂等、管理员登录全部 **PASS**。新租户 `CYRQX6`，application `03e04a8715ae46ca979670c562060371`。
- 新租户自动创建 Maker `001300000001`；运行中 T398 MySQL 读取 `dc_users_symbol_config(CYRQX6,001300000001,BTCUSDT).leverage=100`：**PASS**，证明部署后真实开户不再写 1 倍。
- 后续自动流动性初始化在 `FUND` 阶段失败三次，`TradeSvr.cashIn` 返回 **1003 CLASS_ONLINE_SERVER**；Gateway `GW_METHOD_STATS` 3 次失败、约 1–4 ms 快速回复。最终 `dc_tenant_liquidity_bootstrap` 为 `NEEDS_RECONCILIATION/FUND`，Maker `funding_confirmed=0`。
- `tenant_service_route` 中 CYRQX6 的 MD/ORDER/TRADE 都是 `SYSTEM,enabled=1`；真实 ZK `/MDTService/TradeSvr` 有 A/B 两个注册节点，`TradeSvrA/B` 下也有实例。**1003 的具体 Gateway 选路/连接根因尚未证实**，不能误报为杠杆修复失败，也不能误报资金入金成功。
- 未执行重复入金、手动余额修改、旧账户数据修补，也未调整 Common 或 Trade 风控。禁止手工将已经有持仓的老账户 SQL 杠杆直接改为 100：当前 `TradeCertifiedLeverageAdmission` 对有持仓的杠杆变更明确拒绝，尚未具备 SYMBOL_PARA + POSITION + ACCOUNT_BALANCE 的认证原子重新估值。
- **最终状态**：新开户 100x 修复 + AdminSvr 本地部署 + 真租户初始化数据库 PASS；自动入金→Tape→Robot→成交 E2E 仍 NO-GO；Order/Trade HA 仍未完成验收。
