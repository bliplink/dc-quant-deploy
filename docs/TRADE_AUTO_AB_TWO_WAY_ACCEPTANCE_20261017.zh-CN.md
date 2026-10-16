# Trade A/B 自动双向 HA 验收记录｜2026-10-17

## 不可降低的验收标准

1. 运行中的 Trade Java 自动故障检测、选主、Snapshot+原始 WAL 追平、复制健康证明及 128/128 回迁。测试脚本只能执行故障注入及只读验证，不能修改 ZooKeeper 主权、READY、健康、ACK 或业务数据。
2. Trade A、Trade B 任一节点单独故障时，另一节点可安全继续交易；恢复节点自动追平并以正确 Epoch 成为 Replica。反向重复至少两轮，且旧 Replica 出故障不得阻塞活 Primary。
3. 每轮非空订单、成交、资金、持仓、Projection watermark、Trade journal committed HEAD 必须对账；拒绝无独立可靠证据的追平/晋升。业务持续运行下验证，无丢单、重复成交、双主。
4. 单机 Mac/Colima 的不同容器不能代表独立物理故障域。若仅存一个实际持久副本且存活节点继续提交，第二次同时故障不可宣称零丢失；必须停用业务或使用第三可信持久副本/见证能力。

## 已实测的部分

- 2026-10-17 06:35 CST，Trade-A 的内置 Java 自动回迁调度对每个 P001、P003...P255 使用 B RSA 签名物理镜像证明、源业务锁写入隔离和真实 ZooKeeper CAS，把 B 恢复到 128 个 READY Primary。全量 ZooKeeper 权威读取：A 128/E1 READY；B 128/E3 READY。没有任何验收脚本写 ZK。
- 2026-10-17 06:57 CST 仍为 128/128 READY；Order 128/128 READY；MD 128/128 READY；ZooKeeper/MySQL healthy，宿主机可用约 281 GiB。
- 现网 Trade 镜像仍分别是 `dc-saas/tradesvr:full-src-auto-fenced-fleet-20261017` (A)、`dc-saas/tradesvr:full-src-genesis-admission2-20261017` (B)。
- **反向双向真实接管未通过。** 新只读预检 `scripts/audit-trade-two-way-auto-ha-readonly.py` 读取完整 256 份 ZK 分配、磁盘 Snapshot 与 ZK health：128 个 B 当前 E3 分区的 A 副本仍是 E2 Snapshot；256 个分区无健康记录。脚本禁止直接推导自动主切权限；当前绝不能为了验收强行 SIGKILL B。

## 本轮源码修复和离线验收

- Common [`1648a3b`](https://github.com/bliplink/com.app.common/commit/1648a3b2bfa185b55003454945a6a554683a8f19)：前一代完成的 Common 恢复 Ledger 按 Epoch 持久归档后才允许下一代开始；315/315 测试通过，无失败。macOS 本地 Common JAR SHA256 `6b4bf7aff300e69198587d06e7243c5c9594977b94b82f789f943f370bba12bd`。
- Trade [`11d7015`](https://github.com/bliplink/com.app.dc.tradesvr/commit/11d7015e2a216968b28a7ca20f07a2445e2aad95)：自动故障接管必须具有同 Epoch 的本地 Snapshot 以及完整已提交 WAL 对应 ACK，阻止旧 Epoch 伪晋升。
- Trade [`57c611d`](https://github.com/bliplink/com.app.dc.tradesvr/commit/57c611d8eb8a922c1d1a7508c98f120ef7e306cf)：每次跨 Epoch 新一代都有独立不可覆盖的旧 Snapshot/原始 WAL 封存目录；第一个旧版本 legacy 目录保持可读，后续 generation 目录 `cross-epoch-old-tail-E<old>-to-E<new>`；收据、恢复、Common Ledger 和业务 READY 均引用精确 epoch。已覆盖未完成交易/异常中断目录、复用旧证据拒绝、首次启动兼容、历史完整持久保留，Trade 367/367 全量测试通过。
- Deploy [`101f9fe`](https://github.com/bliplink/dc-quant-deploy/commit/101f9fe9d6c08917c03376d2fbe1d4437ece5f46)：新增纯只读双向状态预检及单测，实机结论阻止不安全 SIGKILL。
- 本地构建候选镜像 `dc-saas/tradesvr:full-src-two-way-ha-candidate-20261017`，ID `sha256:4897e9c6a7fb44b6bbea8103d3b77cea74038c11368b1c8550a39dbc75a329e4`；标签 `dc.release.authorized=false`，使用上述统一 Common JAR，**没有上线，禁止误报部署完成**。
- GitHub Actions **没有执行**。源码分支已 push GitHub。

## 现存不能伪造的关键证明

- A 是 B 的 E3 物理可信副本：B 需要自己的签名源端和读者认证配置，A 需要 B 公钥/自己的读者私钥；自动恢复必须认证下载、按 Epoch 独立封存、在 Common 安装新 E3，然后通过 B 对 A 物理签名回执，真实 ZK 版本固定发布完整 replica health。必须在本机实际完成，不能靠文件复制、ZK 手写或脚本升级。
- 双向身份配置/镜像部署被执行环境安全检查拦截。**没有换工具或拆分操作绕过这一限制。** 现网 B 未取得 B->A 恢复所需完整配置，不能杀 B 测反向。只有该部署得到执行环境许可并实测 256/256 最新 Epoch 副本和真实健康后，才可进入 A/B 双向 SIGKILL。
- 非空业务的持久 ACK、Replica 同步、Projection 权威对账仍未完成，不能仅凭 128/128 ZERO-data Genesis 主权均衡宣称高可用通过。

本报告记录真实通过与未通过边界；不得根据离线单测和镜像标签将 Demo 标成 "双向 HA 已验收"。

## 2026-10-17 07:10 后续：Epoch/CAS 与真实 ACK 水位修复

- Trade [`0607f3a`](https://github.com/bliplink/com.app.dc.tradesvr/commit/0607f3a15a3b05ba73a66b36dfb93ddba9c4a721)：`TradeFailoverControlPlaneClient` 发布健康时读取真实 ZooKeeper 当前 Primary/Replica/Epoch，读健康 znode Stat 并使用 ZK CAS，拒绝晚到的旧主节点、旧 Epoch、同 Epoch 健康 ACK 倒退、角色漂移；实测之外纯单测及 370 项 Trade 回归通过。
- Trade [`a450e61`](https://github.com/bliplink/com.app.dc.tradesvr/commit/a450e617eaccbe45fe2098687e73624e7261cb2e)：副本降级时保留最后一次已 fsync 的健康 ACK 高水位，不再用 degraded seq=0 抹除历史；新健康证明必须补齐先前 committed ACK 水位。371/371 全量回归通过，0 失败。
- 已本地构建 **未授权上线的**最新候选 `dc-saas/tradesvr:two-way-ack-fenced-candidate-20261017`，Docker image SHA `b77f919911ab3d9d036265980dc1000b9b5eae0170883f8d63fe87d9d150104d`，镜像保留 `dc.release.authorized=false` 和 Common 统一 SHA `6b4bf7aff300e69198587d06e7243c5c9594977b94b82f789f943f370bba12bd`。
- 07:10 纯只读复核：现网 A=128/E1，B=128/E3；**B 对应 A 副本 E2 物理 Snapshot 仍为旧代共 128 个，256/256 ZK 复制健康证明缺失**。Trade-A 现网 `trade.cluster.recovery.replica.autoWarm.enabled=false`，Trade-B 现网没有开启 Genesis observer/反向签名源。两端当前容器运行健康，ZooKeeper/MySQL healthy。**最新代码未上 Demo，未运行真实双向 SIGKILL**。
- 双向自动故障切换的实际剩余阻断是物理独立认证与业务副本 READY/健康发布。对既有阻拦的配置/部署不能换方式绕过执行环境安全检查；不能用 Lua、脚本或运维模拟复制完成。先等待受许可的真实双端部署，然后进行本文件所列全部真实双向带单/持仓故障验证。
