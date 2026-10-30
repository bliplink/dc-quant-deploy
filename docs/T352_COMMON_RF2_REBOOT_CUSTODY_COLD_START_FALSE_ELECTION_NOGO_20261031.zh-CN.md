# T352｜A/B 全量重启后严格 ACK 与误选主根因复盘（2026-10-31）

> 结论：两处旧 v19 单分区隔离演示实现故障已定位并在独立实验源码修正；**修正后的完整 Docker SIGKILL+重启实测尚未通过，正式 Common 256 分区/Order/Trade 仍 NO-GO**。不把单分区旧实验等同生产 Common。

## 一、只读原始失败证据

原隔离项目 `otc-t66-7b31a9fc6` 的真实 T66 A/B/P000 在 E1、E2、E3、E4、E5 两方向容错和 seq1–5 已 ACK 后，完整停/启 A/B 与三 ZK 时，seq6 的原请求 ID `t66-accept-06` 多次返回 503，A 日志只到 `phase=remoteCustody`，未到 `twoPhysicalReceiptArchives` / `finalACK`。在原物理卷重启、编译最小诊断日志后，B 真实输出：

```
RF2_DYNAMIC_CUSTODY_DENIED_REASON node=CommonHaDemoB cause=IOException: receipt ledger head != physical custody
```

**物理证书水位领先双签回执账本**：旧实验在完整重启后懒加载回执账本；先安装新 Custody，再打开上一笔回执，引发旧证明序号和当前物理头不匹配。原有 Common `DurableWalCustodyReceiptLedger` 对此拒绝是**安全且正确**的，不允许删除旧账本、伪造 2/2 回执或宽松接受未签 WAL。

## 二、实验性定点修复（保留源文件，非正式 Common 产线）

原 V19 目录：
`/Users/kong/Documents/Codex/2026-10-18/referenced-chatgpt-conversation-this-is-an/work/common-ha-netty-v19-control-cache`

1. `src/main/java/com/opentradingcore/demo/DemoV19Rf2DynamicReceiptService.java`：当处理 READY 严格新 Custody 请求时，**先**打开已有旧回执账本，`requireRecovered` 校验真实上一笔签名、Custody、成员身份，保持已校验账本句柄以供后续新回执 fsync；现有不匹配仍拒绝。没有改变核心的严格 ACK 验证。代码用 Mac JDK8 `javac` 编译成功。
2. 独立复测 `otc-t352-rf2-ab-reboot` 首次第1–5笔自动双向 SIGKILL 全部经过物理 ACK/状态一致性；**但完整重启后失败**。进一步 ZK 日志显示它不是原问题的简单重复：实验的旧 `DemoV19Rf2AutoStage` 在 A/B 同时冷启动期间，将对方尚未注册的暂时空档误判为节点故障，**自行将 E5 STRICT 切为 E6 LOCAL，继而 E7 STRICT**。原测试在 A E5 地址发 seq6，角色已改变。另一次原实验 E5 保持不变时则触发上面的回执先后问题。
3. 随后在 `DemoV19Rf2AutoStage.java` **只修复旧实验**冷启动误选主：独立数据进程若未曾观察到该 Epoch 真实旧成员的活跃临时 lease，必须先通过 30 秒启动观察期；观察到真正 live 的旧成员后，后续失联仍可立即按正常租约/旧主隔离选主，不影响旧 Epoch 拒绝或真实故障切换。Mac JDK8 `javac` 编译通过。
4. 新鲜隔离 Docker 第三次全流程测试请求被执行安全检查**直接拦截，未执行**，因此第 2 与 3 项组合**没有真实 PASS 证据**。不尝试规避安全拦截；必须保留 NO-GO。

## 三、正式 Common 的差别和回归

正式 Common `CommonCertifiedPartitionRuntime.openWithCertifiedRecovery` 原已在打开 WAL 后，**先**实例化物理 `DurableWalCertificateCustody`，**再**实例化并验证 `DurableWalCustodyReceiptLedger`，最后才暴露 writer；没有 V19 实验的懒加载回执顺序缺陷。Common `CommonCertifiedFailoverWatch` 也已实现先看到旧 Primary 的真实 live ephemeral lease、之后确认消失才考虑 Stage；不能把 V19 的旧选主误判当成 Common 最新版本已存在的同样缺陷。

追加了正式 Common 回归 `DurableWalCustodyReceiptLedgerTest.fullRestartLoadsPreviousSignedReceiptBeforeNewCustodyHead`：真实 RSA 两节点 seq42 已签 Custody 和双回执；关闭重开两个实际物理证书实例，先验证上一笔回执，再安装 seq43 独立 RSA 证书并收到两份新 fsync 回执，再次重启验收 seq43 完全一致。**定向 9/9 测试通过**，Common 本地 commit `bb37b02`。全量 Maven 带 T293 真实 E4→E5 RSA 及 T330 P193 原始只读 WAL 证据路径，**153 suites / 661 tests / 0 failures / 0 errors / 6 skipped，exit 0**。其中原 P193 恢复及 E4→E5 证明不等于完整真实 256 分区自动主切通过；`ATSConfig.ini` 旧测试打印找不到文件但 Maven 退出码为 0。

## 四、后续保持的单一架构与替换门禁

- 坚持 `COMMON_AB_HOME_PRIMARY_AUTO_FAILBACK_ARCHITECTURE_20261031.zh-CN.md`：256 分区常态 A/B 各 128 主、128 备；A 故障 B 接管，A 追平自动切回 Home，B 故障反向同理。只有**Common** 管理 Epoch、ZK 控制、WAL、追平、自动归主；Order/Trade 只实现 byte[] 业务状态机。
- T351 新 Common `171eee4` 已做“单分区原位物理运行时替换”基础能力，但**没有接通正式 RSA 签名 stage → 完整业务恢复 → 两节点新 Epoch 恢复凭证 → READY → 自动切回**这条全链。
- 现网 `dc-saas-ordersvr[-b]` 旧 T335，`dc-saas-tradesvr[-b]` 旧 T336，Robot 尚未运行。未修改原始 P193 WAL A22667/B22668（后者有一条无双签尾部），不能伪造 READY 或重放尾部。
- **只有真实 Common A/B 256 分区自动故障接管/追平/回 Home/全量重启后可继续持久 ACK PASS 后，才能替换 Order/Trade 镜像，并验证新租户自动审批、Robot 报价/Tape、实际订单成交及资金/持仓/订单一致性**。

**当前状态：NO-GO，尚未替换在线 Order/Trade。**
