# T320｜Colima I/O 恢复与 Common 真实 A→B→A 自动本地持久化复测（2026-10-30）

## 结论

**Common 使用同一 T319 Common JAR 的真实两次 SIGKILL、自动 E2/E3 LOCAL READY、主备重新加入和 TCP fsync 复测 PASS；严格 RF2 QUORUM 的完全无人值守闭环及正式 Order/Trade 交易仍 NO-GO。**

本轮只修复了 Mac Colima 开发运行环境，执行 Common 已有 Demo 端到端脚本，未改 Common/Order/Trade 业务集群源码、未删正式 WAL/数据库/RSA，未开启 GitHub Actions。

## 原始运行证据

- Common 源码 commit：`838e92f`。
- 本次运行固定 Common JAR SHA256：`d2ce7f87241d2154362e14485b73e9f1269ddb350bbb9019f04454aa7ae7ee7c`，与 T319 Order/Trade 新候选镜像使用的 Common JAR 一致。
- 全新隔离运行目录：`~/.opentradingcore/t124-live-kill-runs/20261030091508/`；原始签名 Genesis、节点 WAL、签名恢复证明、脚本标准输出均来自独立运行。使用已有 A/B/C RSA 密钥只读挂载与 T84 三 ZooKeeper，未复用正式 Demo WAL/命名空间。
- 脚本：`examples/common-only-demo/scripts/verify-real-auto-sigkill-genesis-replay.sh`，开启原有 T125/T126/T127/T128/T129/T130/T270/T272/T275/T276 检查条件。脚本 **exit 0**，执行两次真实 `docker kill --signal=KILL`。
- A 被杀：B 原来已观察 A 存活、Common Watch 自动进入 E2 RECOVERING，Common 恢复原物理 Genesis + WAL 到 `REPLAY_COMPLETE`；独立 C RSA 见证后发布 E2 `LOCAL_DURABLE_ASYNC READY` 并接受真实业务写入，标记 `T275_COMMON_WATCH_THREAD_VERIFIED_E2_RSA_READY=PASS`。A 返回、在线追平 E2，ZK 角色为 Replica。
- B 被杀：A 的 Common Watch 自动进入 E3 RECOVERING，原始 E1/E2 committed 数据恢复并有双签名/C 见证，标记 `T276_COMMON_WATCH_THREAD_VERIFIED_E3_RSA_READY=PASS`；A 发布 E3 LOCAL READY 后继续写入。
- B 随后真实在线重新加入 E3，Common 泛型签名副本安装与自动恢复 Watch PASS；A 新的 E3 seq3 消息通过真实 Common TCP 复制，B 真实 fsync。最终两端业务状态 **total=85、requests=7**，`T272_REAL_A_E3_NEW_BUSINESS_TO_REJOINED_B_TCP_RSA_FSYNC=PASS`。
- 额外对原始 T298/T293 物理 RSA 签署角色互换证明重新执行 `CommonCertifiedStrictRecoveryReceiptRoleSwapTest`：**1 PASS / 0 skipped / 0 failed**，验证假冒 A 与复用 E5 票据授权 E6 被拒绝。其它 Common 测试未在本次宣称完整 RSA 覆盖。

## 同轮 Colima 故障、恢复与风险

- 首次复测在测试 Genesis 初始容器创建时失败，Docker 报 `failed to create temp dir: mkdir /tmp/containerd-mount...: input/output error`。对运行中的 T319 MySQL 执行 `docker exec` 同样报 `/tmp/runc-process...: input/output error`；多个正式 Demo 健康检查显示 unhealthy。**尚未进入当次 SIGKILL 故障注入，不能称作 Common 失败。**
- 确认实际 Docker context 是 **Colima default**（8 CPU、16 GiB RAM、120 GiB 磁盘），不是 Docker Desktop。检查发现 Colima VM 内 `/bin/bash` 也报 I/O error；hostagent 关闭过程出现 `no space left on device`，但不足以直接确定故障根因是 VM 容量还是瞬态底层 I/O。
- 先仅执行 `docker image prune --force`，回收约 **497.2 MB** 的未引用镜像；`docker builder prune --force --filter until=48h` 回收 0。未清理容器、卷、业务 WAL 或密钥。随后使用 `colima stop --profile default` 和 `colima start --profile default` **非破坏性重启**，未 `delete`/重建 VM。
- 重启后 Colima SSH 和 Docker `exec` 再次可用。VM 根分区约 25% 已用，Docker 数据分区约 43% 已用；正式 `dc-saas-{mysql,zookeeper,platform-web,tenant-web,trade-web,public-web}` 在核验时恢复 healthy。
- T84 三个隔离 ZooKeeper 无 restart 策略，手动启动后，只读证实 T318 Order/Trade `/otc/t318-virgin-20261029-r1/{order,trade}/manifest` 的 E2 STRICT READY 分区清单仍存在。T319 独立 MySQL 已恢复并保留 ADL 迁移表；Order/Trade 隔离进程因第一次启动早于 T84 ZK 而出现 `COMMON_CERTIFIED_CENSUS_STARTUP_TIMEOUT`，随后按依赖次序再次启动。正式 Order A 在重启后仍有重启次数增长，**不能宣布正式业务恢复**。
- 进一步只读核查：T319 Order A/B 第二次启动后仍不断尝试业务侧 `localhost:32181` ZooKeeper 并收到 `Connection refused`，当时未观察到新的 Spring `Started OrderSvr`；T319 Trade A/B 出现真实 `Started TradeSvr`，但 Gateway 发现未启用。正式 `dc-saas-ordersvr` 日志出现 `receipt ledger head != physical custody` 且重启计数继续增长。这是本轮新发现的启动/旧持久化阻塞，**不允许通过抹掉 custody 或伪造水位来启动**。

## 未通过项与执行边界

1. 本轮虽然是无人值守 Common 控制线程验签发布 **E2/E3 LOCAL READY**，但并非 2/2 `QUORUM_DURABLE` 的严格未来 ACK；脚本明确显示 `quorum=false rpoRisk=true`。故障期间不能主张副本零丢失保证。
2. 先前 T300–T308 的严格两方向物理签名、6 笔确认事件和签名水位已完成分阶段测试，但严格模式的双物理节点退役、恢复回执、READY 仍由验收进程显式调用。生产常驻 Common 无人干预严格切换闭环继续 **P0 NO-GO**。
3. 正式 `dc-saas-ordersvr-b/c` 与 Robot 停止；新的 T319 环境未接 Gateway/Robot。正式租户注册、自动审批、盘口持续报价、Tape 真实成交、资金持仓一致性和 Order/Trade A/B 自动切换均未通过本轮 E2E。
4. 所有 HA 机制只允许在 Common 修复；Order/Trade 只实现业务 `byte[]` 状态机。不得删除物理水位或签名校验、伪造 READY，也不能在 Order/Trade 新造一套恢复框架。

**验收状态：Common LOCAL A→B→A 真实隔离回归 PASS；严格 Common 全自动 P0、Order/Trade 正式 P1/P2 仍 NO-GO。**
