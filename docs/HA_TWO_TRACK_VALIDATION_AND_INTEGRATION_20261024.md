# OpenTradingCore 两条并行推进路线（2026-10-24）

## 路线一：Common + Demo 快速验证和压测
- 不扩业务功能；Common 承担 Order/Trade 共用的 HA 状态机、Snapshot/WAL/Diff、权限撤销、双 Custody 与严格 ACK。
- 隔离真实三 ZooKeeper、A/B Netty JVM 做 A→B→A 自动故障切换、持续写入、重启追平、旧 Epoch 拒写和精确 WAL/CommitIndex/Custody 对账。单机降级和严格双副本 ACK 分别报告，不以单机降级 PASS 冒充严格多数。
- T82/T83 已完成部分双向切换，T83 严格单条 ACK p50 约 174–293ms、32/group 4 workers 95.1 WAL/s、故障至降级可写约 20–21s；性能 NO-GO。T84 将原隔离 Common 的依赖正式融入最新 Common JAR，重新跑真实测试，禁止只靠 .class 覆盖验收。
- 性能目标：单条端到端 5–10ms 内、批量分摊 <1ms/WAL、故障恢复 <1s、每分区 1–2k msg/s；之后验证 256 分区、10/50/200 租户及 2–3x burst。拆分磁盘 force、签名、TCP 往返与 ZK 控制成本，禁止以安全降级换漂亮指标。
- 记录 p50/p95/p99、TPS、WAL SHA、RTO、RPO、故障注入轨迹；阶段结论必须写明 PASS/FAIL/NO-GO。

## 路线二：Order / Trade 业务集成
- 与路线一并行启动接口梳理、镜像构建、配置预检，但正式 Demo 业务替换需依赖 Common 基础安全和持久化正确性验收，不必等全部极限性能优化才开始代码集成。
- Order/Trade 复用同一个 Common 集群实现，只注入各自状态机 byte[] apply / snapshot / diff / restore，不另造两份 HA 框架；Gateway 仍只透传。
- 先 Order/Trade 非主节点接入、真实严格 ACK、自动 A→B→A 故障/追平，再用测试租户非零资金、持仓、挂单、成交、撤单和机器人持续交易核验；纳入 MySQL/Projection watermark/MD Snapshot/Diff 权威对账。
- 通过标准：无双主、无丢单、无重复成交、WAL/资金/持仓/委托/成交和 Projection 一致；旧主隔离和证书完整验证前不 READY。
- 只使用本地 Maven/Docker 构建；不得启动 GitHub Actions。源码提交 GitHub，不强推覆盖远端。演示测试证据卷保留，需清理时逐项确认。

## 2026-10-24 当前门禁
- Common 最新远端 saas-crypto 510aaee 上的 9 项 HA 提交已推至独立 `feat/common-t82-certified-custody-20261024`，首轮 84 suites / 386 tests PASS；未合并生产分支。
- T84 新集成 Jar 初次启动暴露旧 V19 缺 `DurableWalGroupCommit$Writer`，以及 RF2 单活恢复必须先 `RECOVERING` 非 READY 的兼容性差异；正在隔离分支补齐并复测。不能宣称 T84 故障切换 PASS。

最新 T84 实测见 [COMMON_HA_T84_VERIFICATION_20261024.md](COMMON_HA_T84_VERIFICATION_20261024.md)。Common 集成 439/439 PASS，T84 隔离双向自动主切局部 PASS，端到端性能与正式业务 HA 仍 NO-GO。
