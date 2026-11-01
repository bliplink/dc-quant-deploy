# T396｜Order/Trade 最新 T389 Common 统一镜像部署验收（2026-11-01）

## 用户要求
按 saas-crypto 分支，以最新已跑 128/128 Home 物理验收的 Common 统一部署 Demo Order/Trade；本地构建、不用 GitHub Actions、保留旧数据与回退，不在异常时跳过认证恢复。

## 实际完成
- 采用 `.work/t374-demo-common-ha/target/t389-common-cold-watch-proof-first.jar`，完整 SHA-256 `6b4418f7b1373bb68a9fac4c79aa4406001e1699ec6d9dd080c83323110e2eae`。该 JAR 曾在隔离 Demo+Common 同一三 ZK + A/B JVM 测试 128/128 Home 连续回切签名 PASS；不代表业务集群故障切换 PASS。
- 本地构建 `local/otc-t396-ordersvr:t389-common-t395-business`，基于 T395 Order 时间修复镜像，叠加 T389 Common。
- 本地构建 `local/otc-t396-tradesvr:t389-common`，基于在运 T368 Trade 镜像，叠加完全相同的 T389 Common。
- 使用 docker run --entrypoint sha256sum 校验了两份候选镜像中的 Common JAR，完整 SHA-256 一致。
- T389 Common `CommonCertifiedE2LargeColdHistoryTest` Maven 离线测试退出码 0。
- 保留完整原挂载及环境，创建了未运行的 `otc-t396-order-a-staged`、`otc-t396-trade-a-staged`、`otc-t396-trade-b-staged`。这些只是预创建容器，没有替换正在运行的旧服务。

## Order B 真实试部署 NO-GO
- 原 Order B `otc-t371-order-b-signed-recovery` 之前已退出；T396 用原 B 的 6 个 mount、16 项 env 和 host 网络创建 `otc-t396-order-b-common-trial` 并启动。
- 启动后在真实 Spring Common 恢复阶段失败、容器退出，报 `java.io.IOException: cold E2 history exceeds bounded payload; snapshot required`。
- 最新 T389 中 `CommonCertifiedE2ReplicaHistory.openExistingReadOnly()` 仍对累计在内存中保留的原始双签名业务载荷设置 64 MiB 上限；`OrderCommonFirstReadyWiring` 仍要把原始签名历史的业务 mutations 全部收集后再 apply，因而不能通过直接替换 JAR 恢复过大的老 WAL。
- Order B 此前已证实 256 个 E2 WAL 总约 1425 MiB，最大 P158 388.82、P164 370.79、P048 367.17、P168 298.3 MiB。直接强行放宽 cap 或跳过原始双 RSA 与 ZK 认证不可接受。

## Trade 双节点的不可忽略风险
- 实际在运 Trade A/B 共享原始持久目录，每节点 E2 WAL 约 514.11 MiB，其中 P167=190.85 MiB、P198=158.05 MiB、P081=154.53 MiB 均超过 64 MiB；两节点当前仍运行。
- Trade 同样走 `CommonCertifiedNodeBootstrap.openAndStartWithZkFencingAndReplay`，`TradeCommonFirstReadyWiring` 也全量收集签名状态批次；直接停机换 JAR 后可能同样无法启动。
- 因此 T396 **没有停 Order A / Trade A/B**，也没有把镜像候选误报成已完成 HA 部署。原 Order B 仍停机，T396 trial 同样停机。

## 必须补齐才能统一上线
1. 在 Common 中完成真实可验证的可信 Snapshot + 原始 WAL 增量恢复，或重新执行独立新 namespace 的 E1/E2 双 RSA 认证空数据启动；不能重放旧签名证明或放宽签名、认证和双主门禁。
2. 业务 Order/Trade 的 Spring 冷恢复必须与 Common 的有界恢复机制一致；新版 `openAndStartWithCertifiedAutomaticRecovery` 还要求真正的 per-partition 签名 source handlers 和 recoveryPlans，目前业务仍使用旧入口，不能传空 Map 伪装完成。
3. 在新鲜 isolated Demo 测通 Order/Trade A/B，再切回正式业务；真实订单成交、Robot Maker/Tape、订单/持仓/余额/Projection 以及 A/B 自动 SIGKILL 切换是最终门禁。

## 当前镜像与原服务
- Order 备份：原 T368/T371 镜像与原 B WAL 未删除。
- 正式 Order A 仍为旧 T368（曾观察到 poisoned primary Epoch/writer unavailable）；Order B 仍退出。
- 正式 Trade A/B 仍为旧 T368 且运行；Robot 仍运行容器但近期有 ERROR，不代表交易已恢复。
- T393 Web 当前新版本已发布，本轮未触碰 Web/MD/Gateway。
