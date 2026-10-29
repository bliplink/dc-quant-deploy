# T281–T282｜Common E4 双节点签名基线与真实三 ZooKeeper Stage 认证（2026-10-29）

## 阶段成果

**E4 的两端 opaque business Snapshot fsync/RSA 证明，以及与真实 ZooKeeper 签名 `E4 STRICT RECOVERING` Stage 的交叉校验通过。完整 P0 仍 NO-GO。**

- 新增 Demo 隔离验收 `CommonDemoE4BaselineProcess` 与可复跑脚本 `examples/common-only-demo/scripts/verify-e4-signed-dual-baseline.sh`。A、B 两个**分别启动的 Docker JVM**从既有 E1/E2/E3 原始 WAL 重建 Demo 不透明业务命令状态；只在各自的目录将同一业务快照落盘、fsync，使用各自原有 RSA 私钥签名。Common 原有 `CommonDurableGenesisVoterImage` 与 `CommonCertifiedGenesisQuorum` 负责物理持久证书。业务 Demo 只解释 byte[]，不实现复制/选主/恢复协议。
- 原始输入：`~/.opentradingcore/t124-live-kill-runs/20261029133129`；T281 可核验复跑产物：`~/.opentradingcore/t281-e4-snapshot-dual-jvm/20261029141049`。结果 A、B 重建得到总值 **85**、去重请求 **7**，双方快照 **231 bytes**、SHA256 `a6e76d0b3f001f972fd7d63fee8360151e8db66c400edfbe08904a706833c8f4`；两份 RSA 分别签名通过，双签名 E4 快照被封存并重新打开。成功标记 `T281_TWO_PHYSICAL_JVM_E4_RSA_BASELINE_PASS`。
- Common 增加 **包内**（不暴露业务模块）的 `CommonCertifiedOpaqueHistoricalReplay`：只有给出已经从独立权限链获验的 WAL 前缀 SHA256，才会按完整帧和原序列调用状态机 `apply(byte[])`。输入错哈希、序号超过原始物理 HEAD 时在应用前拒绝。本轮独立 Demo 测试重放旧 WAL 时的散列取自只读证据文件自身，仅属于**隔离数据自检**，不可替代面向生产者的外部 RSA/custody 来源证明；之前的 T279/T278 已另行验证 E3 A/B 独立 RSA 物理前缀。
- Common `CommonCertifiedStrictEpochRearm.requireTwoNodeSignedBaseline` 要求签名的 Stage 目标是 E4 `STRICT_QUORUM` 且 `READY=false`、成员/分区匹配、各自物理根目录不同、双签名快照重新打开后与两个独立 fsync 原始文件完全一致。测试中同目录冒充两份、B 镜像损坏均拒绝，也不会把 ZK 设置 READY。
- T282 隔离实测：在一套**真实三个 ZooKeeper 服务**上执行 E3→E4 签名 `RECOVERING` CAS 后，额外挂载 T281 两份 A/B 快照及封存的双签名证书，再由 Common 校验。输出 `T282_REAL_3ZK_STAGE_TWO_E4_RSA_BASELINE_VERIFIED=PASS snapshotBytes=231 ready=false` 和 `T280_REAL_3ZK_SIGNED_E4_CAS_RECOVERING_NOT_READY=PASS`，进程退出码 0。证据 `~/.opentradingcore/t282-e4-stage-dual-baseline-real-zk/20261029141217`。

## 严格限制与剩余任务

以上为**两个先后运行的独立 Docker JVM、两份各自目录及身份的快照证据**；它们在同一 Mac Docker VM 上，并非跨物理机 HA。T282 的 ZK 验证 JVM 读取两个证据卷，并**没有**分别启动两套活跃 E4 交易节点。ZK 当前只处于 RECOVERING；没有完成两节点独立的 Common 持久恢复事务/正式 `REPLAY_COMPLETE` 门禁，没在此真实进程里执行 A/B 旧 E3 物理 writer close/撤权回执，也没有 E4 READY CAS。

下一项仍是：通过**同一个 Common**让 A/B 真实恢复 E4 baseline、完成签名恢复账本和旧 Epoch fence，核验当前 ZK 授权后才发布 `STRICT READY`；然后在两个独立真实 Netty JVM 上跑 E4 新业务、2/2 WAL fsync、CommitIndex 和双份 Custody ACK，并在真实故障期间重复验证。**任何缺失证明不能靠超时、临时测试脚本或修改订单类型限制绕过。** 历史 E2/E3 的 `LOCAL_DURABLE_ASYNC` 客户端 ACK 永远不追认严格 Quorum。

正式 Order/Trade 容器尚未替换；没有执行 GitHub Actions。项目中原本的其它未提交修改保持不动。

## 本轮完整回归与提交

- Common 本地候选提交：`494d3a9`，分支 `codex/t177-common-saas-crypto-integration-20261027`，候选 Jar SHA256：`158dad3ae641f121e79edcf72e56b009c249c9c87ce51338cdff9eb5fe14bdef`。E4 的原有 signed Stage/CAS 代码仍为 Common 提交 `e754bba`。
- Maven 3.9.16/Java 8 带原有 RSA 的 Common 全量回归：**142 suites、632 tests、632 passed、0 skipped、0 failures、0 errors**，退出码 0。日志中既有 `ATSConfig.ini` 缺失异常输出，但 Maven 没有失败。
- 已加入同一源码仓库的可重跑脚本使用 `OTC_EXISTING_DEMO_RSA_DIR` 和 `OTC_T281_E3_EVIDENCE` 输入；它不使用 GitHub Actions，不清理其它容器数据，也不替换 Order/Trade。
