# T309｜Common 自动 READY 接线阻碍与 Order/Trade 本地构建实测

**日期：2026-10-29｜结论：构建回归 PASS，正式启动/自动恢复/E2E NO-GO。**

## Common HA 实际状态和架构边界

- 此前同一组隔离 Docker/JVM 的 E4(A 主)→E5(B 主)→E6(A 主) 已完成两个方向真实 `QUORUM_DURABLE` 认证写入，六笔已 ACK 命令逐笔唯一，旧 E4 A-only 第三条未确认尾部仍保留且没有被恢复。T308 源码 `b757258`，完整 Common 测试 **638/638 PASS**。见 `docs/T308_COMMON_A_B_A_STRICT_CERTIFIED_6_ACK_20261029.zh-CN.md`。
- `CommonCertifiedFailoverWatch` 已有单一的自动观察→签名 `RECOVERING`→`CertifiedRecoveryCompletion.recoverAndPublish(stage)` 重试控制线程；`CommonCertifiedNodeRuntime.armAutomaticFailoverWatch` 在进入 RECOVERING 后先物理关闭旧 Socket/WAL，再调用完成回调。因此**无需新增任何选主逻辑或 Order/Trade 私有集群**。
- 当前缺口是把真实双物理节点旧 WAL 退休证书、已确认 CommitIndex/Custody、双 RSA 恢复快照与 `REPLAY_COMPLETE` 回执接入 `CommonCertifiedStrictCrashReadyPublisher.publish`；新的两独立 JVM READY 发布仍由 T300–T307 验收流程**显式调用**，尚未在实际业务服务里自动绑定生命周期。不能冒称自动全闭环 GO。
- 尝试添加该 Common 完成回调适配器时，当前执行环境安全检查**阻止了代码写入命令**；没有通过拆解命令规避检查，也没有将未写入、未测试的代码宣称提交。已有 `CommonCertifiedFailoverWatch` 代码未改。

## 本地业务源码构建实测（不使用 GitHub Actions）

| 本地独立模块 | 原始源码版本 | Maven 构建 | 单元测试 |
|---|---|---|---|
| `~/.opentradingcore/t85-business-com-app-dc-20261024` | `com.app.dc:0.0.5-t113-survivor-receipts-20261025-SNAPSHOT` | PASS | 本轮未跑 |
| `~/.opentradingcore/t85-business-ordersvr-20261024` | 依赖上述 `com.app.dc:0.0.5-t113...` | PASS | **54 suites / 167 tests / 163 PASS / 4 skipped / 0 failed** |
| `~/.opentradingcore/t85-business-tradesvr-20261024` | 同上 | PASS | **53 suites / 191 tests / 189 PASS / 2 skipped / 0 failed** |

这只说明 **T113 源码可以稳定编译与通过既有测试**；不是 T308 最新 Common 版本的一致性构建，更不等于正式交易通过。较新 `.work/ordersvr` 和 `.work/tradesvr` 的 `saas-crypto` 源码仍 pin `com.app.dc:0.0.4-SNAPSHOT`，`.work/com.app.dc` POM 仍 pin `com.app.common:3.0.17`；先前旧 T178 集成代码因缺 Common 运行时/API 与当前 RSA 类而构建失败。发布新业务镜像时应锁定一个新的明确源码+Common Jar 版本矩阵并整体本地构建，不能靠旧镜像逐层覆盖 JAR 冒充同版。

## 原运行容器只读诊断

- `dc-saas-tradesvr`、`dc-saas-tradesvr-b` 运行中，镜像 `local/otc-t264-tradesvr:tenant-config`，镜像标签明确 `dc.release.gate=NO-GO`。`dc-saas-ordersvr` 运行中，镜像 `local/otc-t260-ordersvr:certified-e2-prefix`，亦 `NO-GO`。
- `dc-saas-ordersvr-b` 退出码 1，原始日志栈指向 `CommonFileBusinessWal.requireFsyncedPrefix`→`DurableWalCertificateCustody.highestVerified`：**`Common physically fsynced WAL head mismatch`**。这是认证水位保护，绝不能简单去掉校验、重新命名旧 WAL 为已提交，或复用脏数据直接强行 READY。
- `dc-saas-ordersvr-c` 退出码 1，明确 `COMMON_ONLY_LEGACY_CLUSTER_STILL_ENABLED: order.cluster.lifecycle.enabled`。当前实际挂载文件 `~/.opentradingcore/dc-saas-runtime-clean-20261016/control/overrides/OrderSvrC/config/application.properties` **第29行 `order.cluster.lifecycle.enabled=true`**，而 B 使用的 `common-t255-signedmatch-ready/OrderSvrB.ready.properties` 同字段为 `false`。这属于具体配置缺陷；修正新部署模板为 `false`，并清理与 Common 冲突的旧业务集群引用，然后验证新版本 C 启动。
- `dc-saas-robotsvr` 当前退出码 143，停前 Robot 报告 Tape/报价 `IllegalStateException` 和清理失败。**当前没有真实 Robot 持续报价及点价成交 PASS 证据。**
- 上述启动栈和目录已只读核对，没有修改正式镜像、配置和业务 WAL。`compose.yaml` 中提供 `ordersvr-b`、`ordersvr-c`、`tradesvr-b` 等多实例服务，镜像依赖需要统一；`.work` 里保存过 Mac `deploy-saas-macos.sh`，但当前根目录没有同名一键入口，不应宣称现有一键安装已验收。

## 最后 GO 门禁

1. **Common 自动闭环**：同一真实 A/B 集群里自动检测、自动认证安装/双物理 RSA 回执、自动 STRICT READY、继续接受对客 ACK，完整连续双向故障测试，期间没有人工调用恢复/READY 命令。
2. **Order/Trade 统一镜像**：从同一经确认的最新 Common 和业务模块本地编译，清理旧集群配置，使用 Demo 全新可丢数据目录，启动 Order A/B/C、Trade A/B（业务只实现状态机和业务写入，Common 负责所有 HA）；必须真实成功启动才叫部署 PASS。
3. **交易验收**：新租户注册→自动审批→自动启动 Robot→持续盘口/Tape 真实成交→下单/部分成交/撤单/平仓→订单、成交、余额、持仓一致，最后在持续交易中真正 A↔B 自动互切。

**整体 P0 = NO-GO。** 该文档记录了本轮已执行的真实构建、测试和启动故障证据，未冒认新的自动 READY 或正式交易成功。
