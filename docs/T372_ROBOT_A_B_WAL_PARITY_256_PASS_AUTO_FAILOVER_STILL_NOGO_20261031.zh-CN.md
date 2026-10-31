# T372｜保持 Robot 运行下的 Order A/B 恢复审计与自动主切缺口（2026-10-31）

## 本轮实测，不能混淆的三项状态

1. **部分业务恢复运行**：新注册并自动审批的 `EBAUU3`（CRC32 P081，A Home）与 `NWQYBB`（P167，B Home）各有一套 Maker/Tape 已入金的 Robot，真实状态各为 `RUNNING / 40`。RobotSvr 正在运行，A/B Order、A/B Trade 和 Gateway 均有运行中的物理容器。原租户 `C8SMUE` 最新为 `DEGRADED / 0`，不能称所有租户已恢复。
2. **物理 WAL 完整一致**：T371 新容器 `otc-t371-order-b-signed-recovery` 使用独立 `t371-order-b-signed-prefix-20261031/data`，取代失败的旧 `otc-t368-order-b-host`。P168 原始故障表现为 A/B WAL 第 1～3825 帧逐字节一致，3826 开始不同，旧 B 的 Custody HEAD 水位为 3825；旧卷不得破坏。T371 B 重建后，与 Order A 在 P168 的 WAL 和 Custody HEAD 文件哈希一致。新只读脚本扫描 **256/256 分区**，逐帧检查 Epoch、连续序号、物理长度及 CRC，比较 A/B SHA-256 与 HEAD 文件哈希，结果 **0 mismatch**，第二次运行中复核最高观察帧序号 5182，仍为 0 mismatch。模拟匹配、分叉和 CRC 损坏 **3/3 PASS**。注意：脚本不提供 RSA 签名/Quorum 验证，此工作由 Common 正式认证链路负责。
3. **成交历史恢复 PASS，完整 HA 仍 NO-GO**：T369 Projection 曾停留在 18:42，经认证源已就绪后的独立重启，水位推进至 **20:01:59**；新租户 `EBAUU3` 已写入 **246 条执行明细（246 distinct ExecID）**、`NWQYBB` **188 条（188 distinct ExecID）**，旧租户 `C8SMUE` 的 438 条成交历史保留。此前 A 停机故障注入未自动将 P000 转给 B，反而导致 B 被拒写；T371 B 的签名恢复启动不等于自动主切 PASS。当前业务在运行，暂不再次杀掉业务 A/B。

## 自动故障切换代码边界确认

- 当前部署的 Common JAR **已存在** `CommonCertifiedNodeRuntime.armAutomaticFailoverWatch`、`armAutomaticPhysicalRecoveryWatch`、`armAutomaticHomePhysicalRecoveryWatch` 与 `CommonHomeReturnCensus`；这是 Common 的机制，应复用而非重新设计。
- 当前 Order/Trade 的 Spring 接线主要调用 `CommonCertifiedNodeBootstrap.openAndStartWithZkFencingAndReplay`，源码中**未见对这些自动 Watch 的显式激活**。运行期确认证书、Manifest READY 不等于有活跃的故障迁移协调器。应在 **Common 启动与控制面**统一建立 Watch/回放及撤权机制，Order/Trade 仅注入自身二进制状态机、Snapshot/Apply 等业务接口，Gateway 仍只透传并读已认证路由。
- 在独立 Demo+Common JVM/ZK 测试：真实 A 终止→B 撤权/追平/接管→A 返回并逐个 Home 回切；B 终止→A 同样处理。断言 B 原有的 128 个主分区不因 A 故障中断，主备无双主、无重复认证成交；记录全部 128 Home 归位的总时长与 P99。不可人为写 ZooKeeper 的 READY 或跳过签名。
- **当前不要对正在报价的业务 A/B 再停机注入**，优先持续运行现有 Robot。测试及修复在隔离 Common 环境完成后再统一替换。

## 只读验收命令

```bash
python3 tests/audit-t372-common-wal-parity-host.py \
  --a "$HOME/.opentradingcore/t365-ready-20261031-r1/data/OrderSvr/OrderSvrA/OrderSvr/OrderSvrA" \
  --b "$HOME/.opentradingcore/t371-order-b-signed-prefix-20261031/data/OrderSvr/OrderSvrB/OrderSvr/OrderSvrB" \
  --epoch 2 --partitions 256
```

证据限制：物理 CRC/SHA-256 一致性 ≠ RSA 认证或 HA 自动接管通过。保留 T368 B 原始故障卷和提交证据，不能伪造或覆盖历史水位。
