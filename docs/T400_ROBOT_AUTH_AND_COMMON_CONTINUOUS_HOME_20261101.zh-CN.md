# T400｜Robot Runtime 认证恢复与 Demo+Common 持续写入验证（2026-11-01）

## 本轮真实环境

- 分支：`saas-crypto-latest`；本地构建、Docker 实机验证，不使用 GitHub Actions。
- 正式 T399 Demo：`otc-t399-{order,trade}-{a,b}-host`、`otc-t399-gateway-config-t398`、新的 Login/Manager/Admin/APS/MD/Projection、独立 T398 MySQL 与 ClickHouse。
- 独立 HA 测试只运行临时 Demo+Common A/B JVM、三 ZK Docker 与第三只读审计 JVM；其临时 ZK/Docker 测试进程在每轮结束后停止。**未向正式 T399 的 Order/Trade 注入 SIGKILL**。

## Robot 认证修复（正式 T399）

1. 新租户数据仍空，平台/Robot 身份脚本 T399 已将受授权原运行时 API Key 初始化到 T398 MySQL；但这一初始化发生在 Login/Gateway 原启动之后。
2. 启动 `otc-t399-robotsvr` 后真实收到 `gateway rejected robot runtime login: API_NOT_EXIST`，该状态**不是报价成功**。
3. 按原部署机制分别重启新 `otc-t399-loginsvr` 和 `otc-t399-gateway-config-t398`，没有改任何认证逻辑、API Key 或 Gateway 源码。
4. 实际新 Login 日志出现 Robot Runtime API 会话建立；后续 45 秒窗口中 Robot 的 `API_NOT_EXIST=0`、`Robot configuration reconciliation failed=0`、新 Login 的 Runtime Session Cache 记录存在。Robot 新容器运行，但 **没有通过自动审批的新租户，因此持续 Maker 盘口/Tape 成交未验收**。
5. 第一次 `T399AA` 正式 Gateway 申请 HTTP200/code0，但因未带管理员初始密码而维持 `PENDING`；带完整密码的下一次尝试被执行环境安全检查拒绝，没有真实成功回执，不宣称自动审批 PASS。

## T400｜补齐原 T390 的持续可写缺口

**以前的 T390 128 分区回切/单分区首笔严格 ACK 已有独立证据，但临时 Runtime 在每个分区单笔 ACK 后关闭，不能证明其它分区迁移时先前 READY 分区还可写。**

本轮只修改 Common 仓库 `examples/common-only-demo/src/test/java/com/app/common/replication/` 中 3 个 Java 测试类和部署仓库中的 `tests/run-t376-isolated-common-zk-stage.py`，通过显式 `--continuous-writes` 门禁开启；原无该选项的老测试路径保留。

测试改造包括：

- B 的每个 E3 replica 使用独立 TCP 端口 `4612+分区编号` 并一直保持 Runtime/Netty 直到整组分区完成；A 的每个认证 Primary Runtime 同样持续运行。
- 随后每切换一个新分区，对 P000 和前一个分区进行额外真实 `QUORUM_DURABLE` ACK，不向 ZooKeeper 热路径添加业务 RPC。
- **每个物理 JVM 只有一个 Common 节点控制器/续租线程**，各分区不同 WAL/副本状态共享该控制面。相同 ZooKeeper Session 下，全局 Manifest 变化时通过旧 A 原始 RSA 签名 Stage 和双 E3 RSA Recovery/物理证据进行认证刷新；任何涉及已保留分区角色变化或无证据新 READY 均拒绝。
- 两个业务 JVM 停止后，第三独立 JVM 只读核验每分区完整已认证业务命令列表、A/B 物理 WAL HEAD、旧双 Custody 签名，不能仅以客户端 ACK 字符串计 PASS。

### 实际结果

| 测试规模 | 结果 | 第三 JVM 核验 |
|---|---|---|
| 2 分区 | PASS | P000 2/2；P001 1/1 |
| 4 分区 | PASS | P000 4/4；P001/P002 2/2；P003 1/1 |
| 8 分区 | PASS | P000 8/8；P001–P006 2/2；P007 1/1 |
| 16 分区（单节点级共享控制器） | **PASS** | 16/16；P000 16/16；P001–P014 2/2；P015 1/1 |

16 分区证据 `.work/t374-demo-common-ha/target/t376-isolated-zk/t378-signed-auto-home-248a5502.log`：

- `T390_SAME_ZK_HOME_STAGE_READY_PASS`：16 次；`T400_E3_CONTINUOUS_QUORUM_DURABLE_ACK_PASS`：**29 次**额外严格 ACK；
- `T386_INDEPENDENT_3RD_JVM_E3_REAL_TCP_DUAL_RSA_CUSTODY_PASS`：16 次；
- P000 在 P001–P015 迁移过程中，连续新提交序号 2→16，第三 JVM 核验 A/B HEAD 均 16；
- 本轮 A JVM 79652ms、B JVM 80672ms；单分区 READY 时间在本轮 1986–4009ms 之间，**这些不是故障停顿 P99，也不是 128 分区客户时延**。
- 16 分区第一次在 P010 前因每分区独立启动 ZK 控制器出现已认证快照暂时拒写；改为正确的节点级共享控制器后重跑 **16/16 PASS**。这是一项测试体系/控制接线修复，不是暗中降低 Common 拒写门禁。

Common 代码已推送：`bliplink/com.app.common` 的 `saas-crypto-latest`，提交 **`0477ce3`**。

复现（实际 RSA、测试专用证据目录，需已编译测试类；不触碰 T399 业务容器）：

```bash
python3 tests/run-t376-isolated-common-zk-stage.py \
  --mode home256-signedwatch \
  --home-partitions P000,P001,P002,P003,P004,P005,P006,P007,P008,P009,P010,P011,P012,P013,P014,P015 \
  --all-home-watch-pressure --continuous-writes \
  --candidate-jar-name t389-common-cold-watch-proof-first.jar \
  --worktree .work/t374-demo-common-ha \
  --base /Users/kong/.opentradingcore/t177-common-saas-crypto-integration-20261027 \
  --expected-sha256 6b4418f7b1373bb68a9fac4c79aa4406001e1699ec6d9dd080c83323110e2eae
```

## 未完成门禁（NO-GO）

1. 在**同一 256 分区真实 manifest** 上进一步完成 **128/128** 持续写入（不是旧版单笔 ACK 回切）、完整耗时/P95/P99/资源与 A/B 数据审计。
2. 真正 A SIGKILL→B 自动接管→A 追平回 Home，以及 B SIGKILL→A 自动接管→B 追平回 Home，故障期间未影响对侧原 Home 写入、无双主、丢单或重复成交。
3. 正式 T399 新租户自动审批、Robot 自动启动 Maker 报价及 Tape 成交、资金/持仓/Projection 与 MD 行情验收。当前 Robot Runtime 已认证不等于有活跃报价用户。
4. 本轮未修改正式 Common 主干 WAL/HA 机制或重新构建正式业务镜像；新 T400 逻辑为隔离测试代码。不能以测试证据冒充正式业务 HA PASS。

**执行原则：Common 负责所有 HA/快照/WAL/恢复，Order/Trade 只做业务状态机；Gateway 仅认证路由/透传；不添加多余架构或隐式失败自动通过。**

## T400 增补｜Mac 共享目录问题与 32 分区 Docker 原生卷实测

原先使用 Mac bind mount 存放每分区 E3 Genesis/WAL，32 分区第一次在 P010 遇 NoSuchFileException（B 的已写 Genesis 在共享目录中不能立即读回）。**该次 FAIL 不计入 HA 验收。**

修改 tests/run-t376-isolated-common-zk-stage.py 的 --continuous-writes 隔离路径：A 和 B 各自使用独立的 otc-t400-<run-id>-a/b Docker managed volume，双方仍需真实独立 fsync、2/2 RSA、TCP Replica 与第三 JVM 只读审计。原测试路径和实际旧证据保留；生成的新卷不自动清理。

新路径 4 分区回归 PASS；随后同一三 ZooKeeper、两个 JVM 的 **32 分区连续回切及持续写入 PASS**：

- 原始日志：.work/t374-demo-common-ha/target/t376-isolated-zk/t378-signed-auto-home-203dad98.log
- 32 个 T390_SAME_ZK_HOME_STAGE_READY_PASS；**61 次迁移期间额外 QUORUM_DURABLE ACK**。
- 32 个 T400_REPLICA_STILL_LIVE_FSYNC_PASS，32 个第三独立 JVM T386_INDEPENDENT_3RD_JVM_E3_REAL_TCP_DUAL_RSA_CUSTODY_PASS。
- P000 第 2 至第 32 笔迁移期严格 ACK 持续成功，最终 A/B 已认证 WAL HEAD=32；P001–P030 各 2/2，P031 1/1。
- A/B JVM 过程用时分别约 154.7 秒和 156.0 秒（包括签名恢复、测试等待及日志；不是故障断单时间）；单分区 READY 耗时 1988–3572ms，当前 32 样本的 P95 约 3399ms，不能冒充 128 分区 P99。

**仍然 NO-GO：** 128/128 真正持续可写全量、A/B 双向真实 SIGKILL 自动接管/恢复回 Home、真实租户+Robot 交易与资金不变量尚未完成。
