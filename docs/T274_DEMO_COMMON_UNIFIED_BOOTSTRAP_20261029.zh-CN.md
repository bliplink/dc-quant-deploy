# T274｜Demo 与 Order/Trade 统一 Common 正式 Bootstrap（2026-10-29）

## 真实完成的工作

**Demo 曾使用 `CommonCertifiedNodeBootstrap.openAndStartWithZkFencingAndSources`，而 Order/Trade 的正式接线使用 `openAndStartWithZkFencingAndReplay`。二者并未执行相同的启动前业务恢复证明检查。** 已在 Common 单一源码中将这两条接线归于同一个生产入口 `openAndStartWithZkFencingAndReplayAndSources`：

- Demo 调用新统一入口，同时交给 Common 其业务状态已恢复的 `CommonBusinessRecoveryReadiness` 与可选已签名恢复数据源处理器。
- Order/Trade 原有 `...AndReplay` 入口转调同一函数，附空的已签名源处理器映射。它们目前**尚未重编/替换正式镜像**，P1 未开始。
- Common 在创建 WAL/Custody/Netty 前验证业务恢复；实际 Netty 绑定前再次验证。旧无 Replay 的 `...AndSources` 标为 `@Deprecated`，仅供低层协议测试；不允许 Demo/Order/Trade 使用。
- Common 不解析 GTC/IOC/FOK、订单/资金类型，不增加 HA 框架或新的恢复协议；业务只提供 `byte[]` 状态机、业务校验和恢复就绪证明。

Common 源码：`~/.opentradingcore/t177-common-saas-crypto-integration-20261027`；本地提交 `e8672ce`，分支 `codex/t177-common-saas-crypto-integration-20261027`（候选分支，尚未集成到 Order/Trade 的 `saas-crypto` 分支）。

## 构建、测试与实测证据

- 已复用本机 Maven 3.9.16 + Java 8。Common `mvn -q test` 退出码 0：**139 套件、617 测试、0 failures、0 errors**。原始独立 A/B RSA 下重新执行 `CommonCertifiedNodeRuntimeTest`：**12/12 PASS、0 skipped**。Demo 状态机测试与本地 Common Jar 安装、Demo 编译均通过。
- 新增的 `signedRecoverySourcesCannotBypassProductionReplayAdmission` 测试要求：即便注册 Common 已签名恢复源，只要业务恢复未经认证，立即拒绝，不能创建任何物理 WAL 或 Netty 数据。
- 最新候选 Common Jar SHA256：`8504a14d24f25e71d8b9c5e82f4c40cfa23ceb62a492d4d5f54cf3e35766925a`。
- 同一候选 Jar 的**新一轮**隔离 Docker + 真实 ZooKeeper + 原始 A/B/C RSA 验收退出码 0，原始证据：`~/.opentradingcore/t124-live-kill-runs/20261029112936`；总结日志：`~/.opentradingcore/p0-20261029-evidence/t274-bootstrap-parity-real-sigkill.log`。
- 真实 `SIGKILL A`、B E2 READY/本地写 40→60、A 回归、`SIGKILL B`、A E3 READY/本地写至 74、B E3 在线回归、E3 后续 WAL 通过 Common TCP+RSA 到 B 且 fsync：**全部阶段 PASS**。最终 E3 WAL seq=3，双方业务总值 **85**、7 个请求。初始 E1 才是严格 2/2；故障后的 E2/E3 客户端确认仍为 `LOCAL_DURABLE_ASYNC`，不得追认为 QUORUM。

## P0 仍 NO-GO：不能提前替换 Order/Trade

1. Watch→RECOVERING→签名 WAL/业务 Replay→独立见证→READY 与旧节点在线重新加入，目前仍有 **Demo 测试进程串联** Common API、测试脚本启动返回进程；须在正式 Common 常驻运行时中**自主执行**，业务服务只注入自己的 `byte[]` state machine。
2. 双副本恢复后，必须完成经 Common 签名认证的**下一 Epoch/策略**授权，验证**未来**新业务重新严格 `QUORUM_DURABLE` 2/2 ACK、物理两票、无双主、故障负载一致。历史 LOCAL ACK 不得升级保证。
3. P0 GO 后，再将相同 Common Jar SHA、Bootstrap、Watch、恢复与持久化语义集成进 Order/Trade，并删除其任何越界 HA 代码，不得重新开发第二套集群。

本轮未替换 Order/Trade，也未使用 GitHub Actions、未上传 RSA 私钥或原始 WAL。
