# T315｜Order/Trade 私有集群测试清理与完整业务源码回归

日期：2026-10-29；分支：`saas-crypto`。范围：只移除旧 Order/Trade 私有集群测试和修正业务测试的现有类引用/测试数据，不新增任何选主、复制、状态机、WAL、业务功能或服务 API。HA 唯一实现属于 Common。

## 实际改动

- `.work/ordersvr`: 从 `src/test/java/com/app/dc/service/cluster` 删除 30 个旧 Java 测试文件，它们依赖已从服务源码删除的 `OrderPartitionJournal`、`OrderReplicationManager`、独立主备、复制队列、旧日志恢复和 Projection 复制实现。它们的版本不能作为当前 Common HA 的真实验收，不能为凑全量测试而恢复已移除实现。其余所有订单撮合/撤单/幂等/TIF/STP/交易信封/业务状态机测试保留。业务主代码不变。
- `.work/tradesvr`: 同理移除 27 个私有集群测试。对仍有实际业务价值的 `FundingFacadeTest`、`RecoveredRiskSchedulerTest`、`UpdateOrderHandlerPartitionFenceTest`，只把已不存在的 `com.app.dc.service.cluster` 旧类引用改为现有 `com.app.dc.service.state`。业务主代码不变。
- `DataFacadeConfigurationTest`: 某个“已有持仓时修改杠杆”场景仅往 `htSymbol` 放 BTCUSDT，未声明 TENANT_A 已启用该产品。当前生产 `DataFacade.getSymbol(location,symbol)` 正确拒绝未启用的租户产品。只为该测试设置已启用租户的产品 fixture，**不放宽运行时产品启用与租户隔离校验**。

## 验收实测

- Order `mvn -q test`: **39 套件、125/125 PASS、0 skipped/errors/failures**。
- Trade `mvn -q test`: **52 套件、202/202 PASS、0 skipped/errors/failures**。中间单个缺产品 fixture 的测试失败，补齐测试前置条件后全部通过。
- Order 与 Trade 分别执行 **`mvn -q clean package`**，未关闭测试/未跳过编译，各自成功生成 `target/com.app.dc.ordersvr-0.0.1-SNAPSHOT.jar`（约 360 KiB）与 `target/com.app.dc.tradesvr-0.0.1-SNAPSHOT.jar`（约 460 KiB）。
- 对比 T314：此前只能 `mvn clean package -Dmaven.test.skip=true` 构建镜像，本轮已解除这个障碍；仍不代表启动完成或真实业务 E2E 通过。
- 适配器 RSA 仍完全使用之前共享模块 `com.app.dc.security.ExistingDemoRsaNodeIdentity`、`CommonConfiguredNodePeers` 原版签名密钥校验；**没有新 HA 逻辑或额外业务类型限制**。

## 真实门禁状态

- 只在 Mac 本地 Maven 验证，**本轮没有清理/重置正式业务 WAL、没有替换任何 `dc-saas-*` 容器**。
- 还要验证新镜像的完整外部 MySQL/ZooKeeper/Gateway/Robot/APS 依赖；Order B/C 当前旧镜像存在 WAL 认证水位与旧集群开关问题；Robot 尚未恢复真实持续报价与 Tape 点价。
- Common 之前的 E4 A→E5 B→E6 A 双向安全恢复和 6 笔严格物理 ACK 已验证，但认证恢复到 `READY` 的**完全无人工调用自动闭环**、正式 Order/Trade A/B 自动主切和真实资金/持仓/成交一致性尚未完成，**NO-GO**。

## 本地提交

- OrderSvr：`338de8e`，旧 30 个私有集群测试删除。
- TradeSvr：`5f2f884`，旧 27 个私有集群测试删除 + 4 处保留的业务测试兼容更新。
- 这两个提交不会纳入各工作树先前存在的其它未提交文件（例如 OrderCertifiedCancelSaga 相关用户改动）。
