# T392 | iPhone 13 最近成交与 Common 候选验证（2026-11-01）

## 已验证
- T390 隔离 Demo+Common：同一三 ZooKeeper、A/B JVM，128/128 Home 连续物理签名回切及第三 JVM WAL/Custody 审计 PASS；不是持续客户写入或真实双向 SIGKILL 验收。
- 正式 Trade Web 仍使用 local/otc-t391-web:trade-price-time，18088 /healthz PASS，JS main_2026_11_01_13_57_58.js，旧 Web 容器保留为 dc-saas-trade-web-t391-backup。
- iPhone 13 T392：修改 .work/dc-trade-web 的 recentTradeHandler.jsx、orderBook/index.jsx、orderBook/style.less；服务端没有成交时间时显示带 ~ 的本地接收时间，明确为近似值。调整约 175.5px 的盘口列宽。
- T392 Web 6 项现有单测 PASS，build-prod PASS，候选镜像 local/otc-t392-web:iphone13-trade-clock 在 18189 /healthz PASS；Playwright iPhone 13 390x844：200 行最近成交，时间列 67px、完整 HH:mm:ss 可见，样例 ~14:13:00。
- 已构建候选 local/otc-t391-ordersvr:t389-common-candidate 和 local/otc-t391-tradesvr:t389-common-candidate；镜像 Common JAR SHA-256 均为 6b4418f7b1373bb68a9fac4c79aa4406001e1699ec6d9dd080c83323110e2eae。

## 未完成及安全门禁
- T392 Web 正式切换命令被执行环境安全检查阻止；正式 18088 仍是 T391，T392 仅在 18189 供测试。
- Trade B 滚动替换命令被安全检查阻止；Order/Trade T368/T371 容器均未替换，原业务运行未被干扰。
- Order/Trade Spring 启动仍调用 CommonCertifiedNodeBootstrap.openAndStartWithZkFencingAndReplay，尚未接入 openAndStartWithCertifiedAutomaticRecovery 的完整恢复凭据计划。单换 Common JAR 不能宣称自动 HA 生效。
- 持续业务写入、真实 A/B 双向 SIGKILL、正式成交及资金/Projection 一致性、iPhone13 真机 Safari 仍需验收。
- 缺少权威成交时间的行显示 ~ 接收时间，不应宣称是实际交易执行时间。后端 MD/Trade 需补齐权威 TransactTime/MDEntryTime。

执行原则：保留在运业务和旧镜像；不通过改写命令绕过安全检查；Common 统一 HA、Order/Trade 业务状态机、Gateway 不改；本地构建，禁用 GitHub Actions。
