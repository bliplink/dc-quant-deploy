# T522｜Common 候选恢复诊断（2026-11-06）

## 状态：NO-GO（禁止当作 HA 完成）

WebCodex 在 Mac 的 dc-quant-deploy / saas-crypto-latest 分支完成只读核查。四个旧 T488 Order/Trade A/B 容器仍运行；T521 Order/Trade B 候选退出码 1，未替换生产业务容器。

### 已确认的根因

1. T521 Order 启动异常路径：OrderCommonAutomaticRecoveryDependenciesWiring.physicalSignedSources → NodeClusterControlManager.awaitInitialCertifiedPartitionCensus → NodePartitionGrantTable.requireCertifiedCensus；报 COMMON_CERTIFIED_CENSUS_STARTUP_TIMEOUT。
2. 在三 ZK 集群 zk1 上真实执行 zkCli.sh ls，/otc/t521-canary-20261105、/order、/trade 均返回 Node does not exist。因此新候选没有可认证的 256 分区启动目录。不能通过跳过认证或复用旧签名来处理。
3. CommonCertifiedProductionPhysicalRecovery 目前主要支持 E1→E2 的局部路径，仍明确拒绝跨 Epoch READY/业务安装，不能因为 CommonCertifiedCrossEpochSurvivorInstall.installE3OpaqueV2 已存在就声称 256 分区生产恢复执行器完成。
4. 静态门禁 tests/check-certified-auto-recovery-wiring.py 返回 NO-GO；本轮本地 Maven 未在 PATH 中找到，Java 集成测试没有新增 PASS。

### 本轮完成的可复验变更

新增 tests/t522_readonly_canary_zk_preflight.py：使用只读 zkCli get 核对指定隔离命名空间中 NPC1 原始 256 分区 manifest 的结构及 A/B 成员。它不验证 RSA、不创建 ZK 数据、不认证 READY、不替代 Common。

真实 T521 Order/Trade 执行结果均为 NO-GO:T522_CANARY_ZK_BOOTSTRAP:NAMESPACE_OR_MANIFEST_MISSING，exit=2。真实既有 T488 Order/Trade 的 256 分区 NPC1 第 2 代 manifest 作为结构正对照，二者均返回结构校验通过（exit=0），明确不代表 RSA/READY 通过。离线解析测试：合法 256 行 PASS；缺分区、重复分区、错误物理主备成员均拒绝 PASS。初版严格限定 NPC1|1 导致对真实第 2 代 manifest 误拒，已修复为接受正整数代数。

### 后续必须完成

1. 用真实独立 A/B RSA 初始化全新签名原始 Home、Genesis 和认证 ZK 256 分区，不能手写 unsigned READY。
2. 仅在 Common 补齐并验收 E2→E3、后续跨 Epoch 完整 WAL/Snapshot 安装，真实 A→B→A 自动故障切换、追平及回主；不在 Order/Trade 自建集群。
3. 然后才统一 Common JAR、构建替换 Order/Trade，验收新租户、Robot、真实成交、持仓/余额/Projection 一致性。

此文档只记录真实证据；本轮未部署、未切换四个正式容器，也未宣称生产 HA 成功。