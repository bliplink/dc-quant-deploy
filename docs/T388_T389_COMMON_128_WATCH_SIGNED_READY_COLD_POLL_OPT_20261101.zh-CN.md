# T388–T389｜128 个 Home Watch 并发签名恢复与冷控制优化验收

日期：2026-11-01。只在 **隔离 Demo+Common** 操作，业务 Order/Trade、Gateway、Projection、Robot 全程不替换、不重启、不注入故障。

## 本次候选与边界

基准：T143 原始 Common 源码 `908ca02`，隔离工作树 `.work/t374-demo-common-ha`。候选 T389 `.work/t374-demo-common-ha/target/t389-common-cold-watch-proof-first.jar`（SHA-256：`6b4418f7b1373bb68a9fac4c79aa4406001e1699ec6d9dd080c83323110e2eae`）。此 JAR 没有部署到 Order/Trade，不能将本轮验收误报为线上 HA PASS。

### T388：真实 128 Watch 中一个分区具有物理证明

在真实隔离三 ZooKeeper 256 分区 Manifest 上，同时启动 A 原始 Home 的 128 个 Common Watch。其中 127 个**明确没有**签名 WAL/Custody 证明，唯一一个（P063）有 A/B 独立真实 fsync WAL、2/2 CommitIndex/Custody 及 old-Epoch 退休 RSA。

结果：
- 127 个无证明 Watch 均未 Stage、未 READY，255 个其余分区始终保持原 READY；
- P063 自动调用同一 Common 严格链路完成 E3 RECOVERING → 双 RSA image → A/B REPLAY_COMPLETE → 双 E3 RSA recovery receipt → 原有严格 READY 发布 CAS；
- 新 E3 A 主通过真实 Netty TCP 写向 B，得到 `QUORUM_DURABLE` 客户 ACK；
- A/B 写入进程结束后，第三个 JVM 只读重开双方 E3 原始 WAL 与 B Custody/双签安装账本再次 PASS；
- 128 Watch 共用两条冷控制线程，没有 128 个轮询线程。

原始日志：`.work/t374-demo-common-ha/target/t376-isolated-zk/t378-signed-auto-home-d026538c.log`。`T388_REAL_3ZK_128_HOME_WATCHES_WITH_ONE_PHYSICAL_STRICT_READY_PASS activeHomeWatches=128 physicallyReady=1 deniedWithoutProof=127 retainedOtherReady=255 selected=P063 sharedColdControlThreads=2`。**P063 从开始到签名 READY 11,551ms**，暴露冷控制调度拥堵；此结果绝非 128/128 回切。

### T389：优化冷控制的两个局部操作，不增加选主协议

1. 改 `CommonCertifiedFailoverWatch`：Home 分区没有独立实际 WAL 追平证据时，**先在本地 fail-closed**，避免每 250/300ms 对没有资格回切的分区频繁查询 ZooKeeper。仍然**每 2 秒重读一次原始签名 Stage**，保留 JVM 崩溃后凭 RSA/持久化前序恢复未完成 RECOVERING 的能力；完成的 Stage 和真实 READY 无快速通道。具备完整物理证明时，依然执行现有 Common 真实 ZooKeeper lease/CAS/双方 RSA 完整授权链路。
2. 128 Watch 首次启动采用分区号确定性错峰调度，防止同一 JVM 启动时 128 次 ZooKeeper 冷控制探测一起冲击两条共享线程。
3. 测试专用两个 Docker JVM 间的 **auxiliary 文件交接** 改成临时文件写完 `fsync` → 同目录原子重命名，避免用 `Files.isRegularFile` 错把半写入的 RSA 文件当作完整证明。在优化初版真实压力测试中曾抓到 `RSA-2048 Genesis signature required`，A 对 B 已创建但尚未写完的 `e3-vote.rsa` 文件进行读取。修复后多次通过。此文件交接修复**仅是隔离测试夹具**，不替代 Common 的 WAL/CommitIndex/Custody 正式持久化。
4. P001 曾有一次 B `custody-ledger/receipt-quorum.bin` 不出现（旧 Runner 遗漏 B stderr）；本次具体捕获的半文件问题与之症状一致，但**不能凭推断证明之前 P001 那次 30s 超时根因已经全部消除**。Runner 现在保留 B 详细错误日志。

## T389 真实并发复测

使用同一候选 JAR、`--all-home-watch-pressure` 128 个 Watch 的真实三 ZooKeeper + 双 JVM + 第三独立磁盘审计：

| 分区 | 到签名 E3 READY | 同时 Watch | 其余 127 未授权状态 | E3 TCP QUORUM_DURABLE | 第三 JVM 实体磁盘 Custody |
|---|---:|---:|---|---|---|
| P063 | 3,837ms | 128 | 全部未切 | PASS | PASS |
| P001 | 3,992ms | 128 | 全部未切 | PASS | PASS |
| P127 | 3,901ms | 128 | 全部未切 | PASS | PASS |

对应完整原始证据：
- `t378-signed-auto-home-8b08b900.log`（P063）
- `t378-signed-auto-home-54f435c3.log`（P001）
- `t378-signed-auto-home-5d070609.log`（P127）
均在 `.work/t374-demo-common-ha/target/t376-isolated-zk/` 下。

与 T388 优化前 P063 的 11,551ms 相比有明显改善，但**不是同一宿主负载的配对压测，也不是对 128 分区全体就绪时吞吐的证明**。要做真正容量/延迟比较，必须在相同持续负载和同一全量物理环境多次采样，并记录冷控制 ZK QPS 与 P99。

## 回归与安全验收

- T389 完整候选源码 Java 8 编译成功，JAR 校验通过。
- 常规 JUnit：**37/37 PASS**。
- `tests/run-t376-isolated-common-physical-rsa.py`：**discovered=45 executed=45 assumption_skips=0 ignored=0 failures=0**；历史 T322 原始 RSA 退休、双恢复、原始 WAL 与严格 READY 通过。T359 的 128 Home 为**模拟 128 CAS**，不能充当真实 128 WAL。
- 采用优化候选独立真实三 ZooKeeper 运行 `--mode home256`：有 128 Watch 但没有真实 WAL 证明时 0 自动 Epoch CAS；P000 一次可信签名 Stage，P001 并发受单分区 in-flight 门禁拒绝；A 新 JVM 重读旧 Stage，不产生假 READY，全部 PASS。
- 所有实际容器测试均处于独立 Compose project，并在完成后停止；没有变更业务 ZK 根目录。

## 下一步、部署门禁

**整体 HA 仍 NO-GO，Order/Trade 不能在本轮替换。**
1. 当前只有 P000、P001、P063、P127 四个分区在**各自独立隔离集群**完成过物理闭环；128 Watch 并发只有其中 **一个**具备真实物理证据并完成回切。必须实现同一运行中 **128/128** Home 的真实逐分区独立源 WAL、双 Custody/旧 Epoch 退休/E3 状态机双恢复/原始签名 READY，统计全体总耗时与实际连续 ACK、未回切分区仍可写。
2. 真正的 A/B 故障双向循环（A 主停止→B 接管→A 追平→回 Home；B 停止→A 接管→B 追平→回 Home），持续负载，核对 256 物理分区 Wals/Custody 与业务不可重复执行。
3. 已在运行的业务版本继续提供 Robot 交易。全部 Common+Demo 真实完整门禁 PASS 后才打包同一公共 JAR，统一部署 Order/Trade 并验收新租户自动审批、Maker/Tape、交易结算、Projection 及双向 HA。

命令：
```bash
python3 tests/run-t376-isolated-common-zk-stage.py \
  --mode home256-signedwatch --home-partition P063 --all-home-watch-pressure \
  --candidate-jar-name t389-common-cold-watch-proof-first.jar \
  --worktree .work/t374-demo-common-ha \
  --base /Users/kong/.opentradingcore/t177-common-saas-crypto-integration-20261027 \
  --expected-sha256 6b4418f7b1373bb68a9fac4c79aa4406001e1699ec6d9dd080c83323110e2eae
```
