# T402｜T401 Common 全 128 Home 验收、双向 SIGKILL、Order/Trade 正式 Demo 镜像替换（2026-11-01）

## 128/128 Home 连续严格持久写入——PASS

- 真正独立的三个 ZooKeeper JVM、A/B Common JVM、Docker 物理数据卷，使用已核验的本地 T401 Common JAR SHA-256 `135ec1c31d15b3992aa3fb69ae10b733aa0e48ab762928db236f55831f9b87bb`。
- 对原始 A Home `P000..P127` 连续 128/128 执行签名 E3 RECOVERING→READY、真实 TCP 双 RSA WAL/fsync/CommitIndex/Custody strict ACK；在其它 shard **处于 RECOVERING** 时，对原先 READY 的 P000/上一 shard 追加真正业务 WAL。
- **127** 个 RECOVERING 交错窗口；**253** 次已 READY 分区跨迁移的额外 `QUORUM_DURABLE` 提交；第三个只读 JVM **128/128** 原始物理 WAL + CommitIndex + 双 Custody 审计全部通过。
- P000 原始 A/B E3 WAL、CommitIndex 和 Custody 最终已确认 **128/128** 条一致；上次真正不确定 WAL 的失败样本仍保留而未误判 ACK。
- Common 授权刷新等待最大 **45ms**，总共 51 次可观察的前 WAL 临时授权拒绝及后续重新认证（**不等于客户请求 P99**）。
- A/B 同一批 JVM 连续返回 Home 用时约 **724615 / 725665ms**（RSA/fsync 隔离测试全流程；不能宣称服务停机如此久）。
- 完整驱动退出码 **0**，最终 `T390_SAME_ZK_ALL_HOME_PHYSICAL_THIRD_JVM_AUDIT_PASS total=128`、`T376_ISOLATED_ZK_STOPPED True`；原始证据：
  `.work/t374-demo-common-ha/target/t376-isolated-zk/t378-signed-auto-home-4a9cdc36.log`。
- 本隔离夹具仍使用每 shard 的 TCP Listener 验证 128 个独立物理 Runtime，关闭过程比生产 Common 节点级共享 TCP Listener 慢；**不能当作正式生产架构的端口/线程拓扑**。

## 双向真实 SIGKILL——恢复链路 PASS，严格零 RPO NO-GO

使用同一 T401 JAR，单独启动 3 节点隔离 ZooKeeper，执行 `tests/run-t376-isolated-common-zk-stage.py --mode signed-cycle`，脚本退出 **0**；原始证据：
`.work/t374-demo-common-ha/target/t376-isolated-zk/otc-t376-c9cc7a64.log`。

- 真正 SIGKILL A → B 自动 Watch、E2 RECOVERING、合法持久化重放与单节点 Local ACK；A 重返并追平。
- 真正 SIGKILL B → A 自动 Watch、E3 RECOVERING、E1/E2 WAL、Genesis、RSA/证明的重放；A 恢复 Local ACK；B 返回并通过实际 TCP 收到 A 的新 E3 WAL/fsync。
- **明确 LIMITATION：** 中间降级 ACK 为 `LOCAL_DURABLE` 且有 `RPO>0` 风险。这个测试没有证明整个故障过程中全程严格双节点 Quorum ACK，也没有证明业务 Order/Trade 双向 SIGKILL 之后资金持仓一致，不能宣传“全面 HA PASS”。

## T402：最新 Common 已部署 Order/Trade A/B

- Mac 本地离线 Maven 构建 T401 Common；Common GitHub `bliplink/com.app.common` 分支 `saas-crypto-latest` 已推送 `caf034c`（新增仅对明确副本预 WAL、无写入授权拒绝允许有限相同帧重发；未知尾部禁止重试，单测 3/3 PASS）。
- 本地使用先前经过业务镜像验收的 `local/otc-t396-ordersvr:t389-common-t395-business` 和 `local/otc-t396-tradesvr:t389-common` 作基底，仅替换各 `lib/com.app.common-3.0.22-t143-durable-signed-crossjvm-handoff-20261026-SNAPSHOT.jar`，镜像内 Common SHA-256 均与 T401 精确一致。
- 新镜像 `local/otc-t402-ordersvr:t401-common`、`local/otc-t402-tradesvr:t401-common`；四个新容器 `otc-t402-{order,trade}-{a,b}-host` 复用 T398 全新业务数据卷、ZooKeeper 原来的三条 `ExtraHosts`、原 host 网络和认证控制配置，四份环境变量集合和挂载均与旧 T399 相同（顺序不同但值相同）。
- 操作时停止旧 `otc-t399-{order,trade}-{a,b}-host`，并实际启动新四容器；保留旧容器/镜像/WAL。四个 T402 Spring 都实际启动，均产生 `COMMON_GATEWAY_CERTIFIED_PARTITION_ROUTING_PASS partitions=256`，检查错误数 0。
- Gateway `otc-t399-gateway-config-t398` 保持不改代码、不改配置；看到旧端点 33036 / 33041 / 33037 / 33046 通道关闭并重建 Discovery，最近 75s 的日志检查 ERROR=0。
- 重新启动 `otc-t399-robotsvr`，Robot、Login、Gateway 均 RUNNING，最近日志 `API_NOT_EXIST=0`、协调错误=0。此处仅代表 Runtime 认证进程恢复。

## 未完成／NO-GO

- 全新 T398 MySQL 实际 `dc_tenant=0`、`dc_tenant_robot=0`，所以 **尚未**真实验收新租户自动审批、Maker 盘口持续报价、Tape 成交、资金仓位与 Projection 一致、iPhone 13 最近成交时间/价格修复。
- 前轮不带 `admin_password` 的测试租户申请 `T399AA` HTTP code=0 但数据库状态 PENDING。完整管理员密码注册调用受执行环境安全检查拦截；未尝试绕过安全检查，不把注册或审批记作 PASS。
- 需要经正式租户注册自动审批（不能人工批准代替），然后 Robot Maker+Tape E2E，并在实际 Order/Trade A/B 进行双向 SIGKILL、Snapshot+WAL Catchup、Home 回切、资金/委托/持仓/成交/Projection 一致性验收。
- GitHub Actions 未使用。本地 Demo 业务数据未清除；仍是全新 T398 空库。以上 PASS 仅针对其实际所测范围。

## 代码及引用

- Common：`bliplink/com.app.common` `saas-crypto-latest` commit `caf034c`。
- 部署：`bliplink/dc-quant-deploy` `saas-crypto-latest`，T401 16 Home 证据 commit `68ff679`，本 T402 文档记录扩展到 128 Home 和真实镜像替换。
