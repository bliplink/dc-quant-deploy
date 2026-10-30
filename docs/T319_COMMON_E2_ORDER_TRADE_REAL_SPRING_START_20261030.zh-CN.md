# T319｜Order/Trade 使用同一 Common E2 完成真实业务启动

日期：2026-10-30。**实际结果：新隔离环境的 Order A/B、Trade A/B 四个 JVM 全部 Spring 启动 PASS，四套独立原始 RSA 身份及 E2 物理 WAL 256/256；正式 Demo 对外交易和 A/B 自动切换仍 NO-GO。**

## 统一边界和现有 E2 来源

- 沿用 T318 原有独立三 ZooKeeper 实例及 `/otc/t318-virgin-20261029-r1/{order,trade}`，各 256 分区 `generation=2`、`ZK version=1`、原始 A/B 双 RSA 首次 E1→E2 READY 票据及双物理 Genesis 全部由 Common 已签署验证，不复用历史正式 Demo 命名空间或旧 WAL。
- **全部 HA 在 Common**；Order/Trade 不新增选主、复制、Recovery、特殊订单类型限制；它们继续只提供业务字节状态机、撮合、结算等原有业务逻辑。Gateway、Robot、ClickHouse 真实 E2 业务端验收暂未连接。

## 排除的两项真实 Common 接线阻塞

1. 第一次用 T318 READY 进入 Spring，`CommonCertifiedNodeBootstrap` 在 `DurableWalCommitQuorum.Membership` 抛出 `invalid RF2-or-more durable data membership`。原因是 `CommonCertifiedPartitionAssignments` 把 Common 已认证分区转成业务 DTO 时没有填写 `assignmentVersion`（默认 0）。仅在 Common 内将原已认证的分区 Epoch 写入对应 DTO 版本，原业务代码不变。增加 Common JUnit 检查 E1、E2、E5 正确映射。
2. 上述修复后，Spring 实际打开了初始物理 WAL，但尚未将 `CommonOriginalFirstReadyBusinessGate` **真正完成的原始 E1→E2 RSA、双物理 Genesis、零 WAL、Spring 实际状态**认证证据传入**同一个 Common** 物理 Replica 启动器，因而 `Common newer Epoch replica certified recovery required` 正确拒绝。仅在 Common 增加原首启 E2 **空 WAL** Replica 的受约束证明传递（已有 `CommonCertifiedStrictReplicaAdmission.Verified` 与原 `CommonCertifiedNodeBootstrap`）；必须满足 **epoch2/config2、原 A/B 身份和两个不同物理槽、RSA pinned public、当前 real ZK session 与 E2 manifest version1、256 分区、精确 Replica 角色、空的本地 E2 WAL、已经完整校验的原有首次 READY 票据与实际 Spring 零状态**。已存在非零 WAL、后续 Epoch 或其它缺证场景继续原认证路径，不允许无签名 READY 或 Replica 直接入场。

## 代码及完整回归

- Common 本地提交 `838e92f`；Maven `test`：**150 suites / 647 tests / 642 PASS / 5 skipped / 0 failures / 0 errors**；`mvn -DskipTests install` 成功。
- Order 原业务主代码仍 `b96bd26`；`mvn clean package`：**126/126 PASS**。
- Trade 原业务主代码仍 `f9a0e9f`；`mvn clean package`：**203/203 PASS**。
- 两个新版隔离镜像 `local/otc-t319-ordersvr:virgin-e2-replica`（`sha256:7ec36ad4d2beb7480c8c6a56c4656f506071c32d56f3460c779ea859c9c9fcd5`），`local/otc-t319-tradesvr:virgin-e2-replica`（`sha256:c280e59da7c1892836f0767a452cbd893924a04e61c3ea0232b5307b1446e567`），内部**唯一同一 Common JAR**，SHA256 `d2ce7f87241d2154362e14485b73e9f1269ddb350bbb9019f04454aa7ae7ee7c`。都保留 `dc.release.gate=NO-GO`、`authorized=false`。

## 完全隔离的真实容器启动

- 新业务测试根 `~/.opentradingcore/t319-business-ready-20261030/`，单独新物理 WAL 根 `t319-ready-v4`；以独立容器名、端口、原 A/B RSA 只读密钥、T318 Genesis/首次 READY 只读材料、真实三 ZK 启动；新服务的 Gateway 发现**明确禁用**，不会向正式 Gateway 注册覆盖运行中的业务节点。
- 原 Demo MySQL 运行在 Mac host 网络；桥接容器访问原 `127.0.0.1:33306` 被拒绝，属于隔离网络差异。使用 Docker 已缓存的 `mysql:8.0.36` 镜像启动独立 `otc-t319-mysql`，仅使用项目已有 `mysql/init/{00-databases,10-dc,11-tenant-control-plane}.sql` 及测试环境**特有** MySQL 8 初始化用户前置条件（生产 SQL 未改）；在隔离 MySQL 成功创建 `dc`、`event`。测试专有数据库密码保存在本地 0600 文件，**绝不放入代码提交**。DBPool 测试配置沿用原始 INI 精确键名大小写、只换 isolated 主机与测试凭据；ClickHouse 测试连接关闭。正式 `dc-saas-mysql` 未更改。
- 实际日志出现：Order A `Started OrderSvr in 8.883 seconds`，Order B `Started OrderSvr in 11.967 seconds`，Trade A `Started TradeSvr in 10.333 seconds`，Trade B `Started TradeSvr in 10.882 seconds`。四套真实 JVM 都继续运行，分别生成 256 个独立 Epoch2 `business.wal` 路径；**共 1,024 个物理分区副本**。
- 从同一隔离 Docker 网络对真实物理 Common TCP 实例执行非业务连接探针：`otc-t319-order-a:45322`、`otc-t319-order-b:45323`、`otc-t319-trade-a:45222`、`otc-t319-trade-b:45223` **全部 TCP_OPEN**。这个探针不代表交易消息或业务 ACK 已通过。

## 仍未验收，严禁夸大

- 这只是隔离环境真实 **Common E2 + Order/Trade Spring/DB/Netty**；新业务并未接正式 Gateway/Robot/APSSvr/MD/ClickHouse，也未进行真实下单、成交、撤单/平仓、资金及持仓对账。**Robot Tape 报价仍未恢复。**
- 新隔离四实例没有经过业务流量中的主动 A→B→A 故障注入，没有无丢单/无重复成交/无双主证明；不能据此宣布正式 HA GO。
- 正式 Demo 的 `dc-saas-ordersvr`、`dc-saas-tradesvr`、`dc-saas-tradesvr-b` 仍是之前镜像运行中；旧 `dc-saas-ordersvr-b/c` 退出，`dc-saas-robotsvr` 停止。**本轮没有替换正式服务、旧 WAL、数据库或租户数据**。
- Mac 磁盘曾只剩 116 MiB；仅删除 38 个 2026-10-11 旧工作树的**可重新编译的 Maven `target`**及四份当前可重建的依赖副本，曾恢复约 3 GiB 空间。原始源码、Git、正式数据卷和 T318 原始 RSA 证据未改。
- 因远端 `saas-crypto` 跟踪分支与本地严重分叉，本轮只在**本地 Git**提交，不使用 GitHub Actions、不强推。

**下一阶段门禁：**在完整隔离交易环境把 Gateway→新租户自动审批→Robot 报价/Tape 点价→真实下单成交→交易时 Order/Trade A/B 自动互切→订单/成交/资金/持仓一致性全部连续验证；全 PASS 后才允许替换 Demo 现有容器。若测试数据可丢，用原 Mac 一键部署脚本重新注册租户，不引入任何额外业务或 HA 机制。

## 2026-10-30 隔离环境复核与修复（不构成正式 GO）

- WebCodex 再次实际核查 `otc-t319-order-a/b` 与 `otc-t319-trade-a/b` 四个容器：全部 `running`，退出码 0，四台都有真实 Spring `Started` 日志；后续最近 30 秒 `ERROR` 均为 0。仅证明启动稳定，尚无业务交易 ACK 证据。
- 发现本轮隔离 `otc-t319-mysql` 缺少 `dc_bankruptcy_transfer` / `dc_adl_execution_v2`，导致 Trade A/B `PendingPositionAdlRecovery` 循环报 SQL 缺表错误。对**隔离数据库**执行仓库现有 `mysql/migrations/20260904_01_bankruptcy_insurance_adl.sql` 后，两表可查询且当前各 0 行，Trade A/B 最近 30 秒不再报告该错误。没有改正式 MySQL、业务代码或 Common 门禁。
- Mac 数据盘仅余约 115 MiB 时，删除 `.work` 下若干**可再编译** Maven `target` 与 `~/.opentradingcore/local-ha-*20261011/source/{tradesvr,mdsvr}/target`，可用空间恢复到约 4.2 GiB。原源码、Git、容器、数据库、RSA、WAL、原始 HA 证据均保留。
- 正式 `dc-saas-ordersvr-b/c` 与 `dc-saas-robotsvr` 仍退出，隔离环境未接正式 Gateway/Robot。Common 严格模式从 `SIGKILL` 到 `READY` 的完成操作在 T308 测试流程中仍显式调用；无人值守 A→B→A 并在线双向重新追平尚缺完整 P0 证据。因此正式 Order/Trade 恢复及业务 E2E **继续 NO-GO**。
