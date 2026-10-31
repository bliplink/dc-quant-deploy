# T373｜部署中的 Common 自动 Failover Watch 接线审计：NO-GO（2026-10-31）

## 业务服务保持运行

2026-10-31 20:16 CST，实测 Order A、T371 Order B、Trade A/B、Gateway、Projection、RobotSvr 全部运行；`EBAUU3` 和 `NWQYBB` Robot 均为 `RUNNING / 40`，执行历史分别为 606 和 408 条，之后继续增长；原租户 `C8SMUE` 为 `DEGRADED / 0`。**在隔离 Common 验证完成前，不对这套正在交易的节点做停机注入**。

## 检查方法和实测证据

新增 `tests/audit-t373-common-auto-failover-startup.py`；只读取已部署 Common JAR 的 `javap -c -p` 字节码，以及 Order/Trade 的 Java 接线源码；不修改 ZooKeeper、WAL、路由和运行容器。测试 `tests/test_t373_common_auto_failover_startup.py`：**4/4 PASS**（无 Watch 识别、真正调用识别、仅方法声明不误报、注释不误报）。

Order 与 Trade 当前安装的 Common JAR 一致，SHA-256：
`7cbe13f614f0abd478b02188e15660b572f1c4519866684c3b308e92593784e6`。
实际版本：
`com.app.common-3.0.22-t143-durable-signed-crossjvm-handoff-20261026-SNAPSHOT.jar`。

审计结果：

- `CommonCertifiedFailoverWatch` 在 Common JAR 中存在，含 `start()`，可实例化；`CommonCertifiedNodeRuntime` 暴露 `armAutomaticFailoverWatch`、`armAutomaticPhysicalRecoveryWatch`、`armAutomaticHomePhysicalRecoveryWatch`。
- `CommonCertifiedNodeBootstrap` 共两个 `openAndStartWithZkFencingAndReplay*` 入口：**0 个 Watch 激活调用**。
- `CommonCertifiedNodeRuntime.start()`、`startWithBusinessReplay()`：**0 个 Watch 激活调用**。当前 `startWithBusinessReplay` 仅完成认证/业务恢复门禁，启动 Netty listener，然后标记 `started=true`。
- Order 现有 118 个、Trade 167 个 Java 源文件：**0 个调用** `armAutomatic*Watch(...)`。
- 结论：已部署应用路径**没有证据显示自动切换 Watch 被激活**。审计退出码 2，`NO_GO_NO_AUTO_FAILOVER_WATCH_WIRED`。即使 ZooKeeper 分区 Manifest 显示 READY，也不能宣布自动接管。该结论与 T370 停止 Order A 后未自动接管的实测吻合。

补充：保持 Trade A/B 运行时，对其真实落盘目录运行 T372 物理审计，**256/256 分区、0 mismatch**，最高 WAL 帧序号 2065。Order/Trade 使用相同 Common JAR，但 **数据一致不等于自动主切已启用**。

## 修复方案只放在 Common（不改变业务边界）

1. 取得与上述部署 JAR **完全对应的、可重现编译的 Common 源码**；当前部署检查使用的 `.work/app-common` 工作树不包含 `CommonCertifiedNodeRuntime.java`／`CommonCertifiedNodeBootstrap.java`，不得假装修改旧 Common 代码就是改了已部署类。不得通过运行时反射、对运行中容器热换类或篡改签名替代真实修复。
2. **Common 启动时统一激活控制面**：真实物理 WAL 和签名 HEAD 校验、Snapshot+WAL 业务回放、Netty 服务认证就绪后，由 Common 负责建立 `CommonCertifiedFailoverCoordinator`、独立的 `LocalReplicaCatchupProof`、持久化恢复阶段 Ledger、真实旧主撤权和认证新主恢复完成回调，再以现有 `CommonCertifiedNodeRuntime.armAutomaticPhysicalRecoveryWatch` 激活非主副本的监控。Home 节点复归使用 `armAutomaticHomePhysicalRecoveryWatch` 和原始分区 Home Census。原有签名/多数认证拒绝保护必须保留。
3. 启动门禁区分 **业务可写 READY** 与 **HA 自动迁移可运行**：真实副本 Catchup/健康证明和对应 Watch 注册计数必须可观测；没有 Watch 时不能宣布 HA READY。按节点批量处理 ZooKeeper 控制事件，不把 ZK 放进订单、WAL 复制热路径，也不要为每个业务进程新增选主算法。
4. Common 必须继续支持一侧故障时另一侧自己 Home 的 128 主分区正常写入。发生故障只转移故障方的 128 分区，保留未失效方独立提交；避免重入、旧 Epoch 接管和交叉租户误路由。
5. 在 **隔离的真实 Demo+Common 两 JVM + 独立 ZK** 先验证 A 下线→B 接管全部 A 主分区→A 追平并自动回 Home，然后 B 下线→A 接管→B 追平回 Home；每次记录 **0～128 已切换数、总耗时、最大单分区延迟/P99**。检查委托、成交、余额、持仓、Projection 和物理 WAL，保证无丢单、重复成交、双主、未经认证的 READY。
6. 上述严格验证成功后，Order/Trade **只注入业务状态机接口**、替换采用同版 Common 的构建，Gateway 继续通过 Common 已认证 ZK 路由透传。现有 Robot 不参与开发阶段故障注入。

## 可重现的只读门禁

```bash
python3 -m unittest -v tests/test_t373_common_auto_failover_startup.py

python3 tests/audit-t373-common-auto-failover-startup.py \
  --container otc-t368-order-a-host \
  --jar /srv/dc/dc/OrderSvr/lib/com.app.common-3.0.22-t143-durable-signed-crossjvm-handoff-20261026-SNAPSHOT.jar \
  --order-src .work/ordersvr/src/main/java \
  --trade-src .work/tradesvr/src/main/java
```

门禁在有源码接线后也只升级到 `SOURCE_WIRING_PRESENT_NEEDS_REAL_FAILOVER_TEST`；**字节码存在激活代码 ≠ 自动故障切换已通过**，必须做真实隔离停机测试。

**当前结论**：两套新 Robot 持续运行；物理 WAL 256/256 一致（T372）；T373 自动主切功能仍 **NO-GO**。不得将现有 RUNNING / READY 标记成自动主切已验收。
