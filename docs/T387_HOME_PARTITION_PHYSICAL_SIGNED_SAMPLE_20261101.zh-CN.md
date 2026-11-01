# T387｜Home 代表性分区全链路采样（P000/P001/P063/P127）

日期：2026-11-01。所有验证在隔离 Docker 三节点 ZooKeeper 和独立 A/B Docker JVM 上进行；在线 Order/Trade/Robot 及安装 Common JAR 未替换。

## 范围

将 T381–T386 真正物理流程从固定 P000 参数化为 `--home-partition P000..P127`，不同 JVM 从 `OTC_T385_PARTITION`读取目标，并严格限制到原 128 Home 分区。每次使用新的独立 ZooKeeper project/namespace、A/B 数据目录、签名 Stage、源 WAL 和 E3 严格 READY；原 255 个不相关分区继续 READY。流程必须包括：
- A/B E2 独立 fsync 原始 WAL + 2/2 RSA CommitIndex/Custody；
- 旧 B 继续在线，目标分区 E3 自动 RECOVERING；
- A/B 关闭各自该分区旧 WAL、签发旧 Epoch 双退休收据；
- 双物理 E3 Image fsync 和双 RSA 封存，双业务状态机恢复 REPLAY_COMPLETE，双恢复 RSA 收据；
- Common Watch 自动发布该分区 E3 STRICT READY；
- E3 A→B 正式 Netty TCP 物理复制，客户 2/2 `QUORUM_DURABLE` ACK；
- A/B 写入 JVM 退出后，第三独立 JVM 只读重开两份 E3 WAL、Replica Custody 与 2/2 安装收据账本并验证准确已提交指令。

命令示例：
```bash
python3 tests/run-t376-isolated-common-zk-stage.py --mode home256-signedwatch \
  --home-partition P127 \
  --worktree .work/t374-demo-common-ha \
  --base /Users/kong/.opentradingcore/t177-common-saas-crypto-integration-20261027 \
  --expected-sha256 dabbd5feceb577394e64cc299354b7f2060a85d4399d4e12b14a9663da8c33a0
```

## 最新实测

| 分区 | 本轮真实 E3 READY | 新 E3 TCP 2/2 ACK | 第三 JVM 磁盘 Custody | 证据 |
|---|---:|---|---|---|
| P000 | PASS，2.106 秒（前一轮） | PASS | PASS | `t378-signed-auto-home-8445aa31.log` |
| P001 | PASS，1.908 秒（第一次成功复测） | PASS | PASS | `t378-signed-auto-home-03eda9ea.log` |
| P001 | PASS，2.356 秒（再次复测） | PASS | PASS | `t378-signed-auto-home-9b1070c3.log` |
| P063 | PASS，2.935 秒 | PASS | PASS | `t378-signed-auto-home-c1c14e5e.log` |
| P127 | PASS，2.011 秒 | PASS | PASS | `t378-signed-auto-home-971457ad.log` |

日志均保存在 `.work/t374-demo-common-ha/target/t376-isolated-zk/`。上表 READY 耗时只包含**该单分区**，不包括新 E3 客户 TCP 写入或三 JVM审计，不能当作完整 128 Home 切换总耗时。每行是**独立重建的隔离 ZooKeeper 集群**，并非同一运行中 128 个分区的连续互切。

## 发现一项间歇测试时序失败（仍需跟踪）

在 P001 的更早一次试跑 `t378-signed-auto-home-93d123b2.log` 中，A/B 原始 WAL及单方 Custody 签名已实际生成，但 B 的 `custody-ledger/receipt-quorum.bin` **在 A 的 30 秒等待内未出现**。正确拒绝 READY；A 进程返回错误且隔离测试结束。此次 Runner 原先遗漏 B 进程 STDERR，无法从旧测试回溯根因（可能是物理文件挂载可见性、进程调度、双收据时序或异常，**不能无证据归因**）。已修复 Runner：保存并在失败时显示 B STDERR，后续每次遇到同类异常均可直接定位。两次随后的 P001 成功，**不等于已经修复第一次失败的根因**；本项列为未消除的稳定性风险。

## 128 Watch 控制面已验证，不代表 128 已回切

`t377-home-control-fc223eb4.log`：128 Watch 同时运行，共享控制线程=2，无物理签名证明时拒绝所有 128 回切，所有 256 分区保持 READY；第一项签名 Stage 完成后，第二项在 in-flight=1 门禁下拒绝、255 分区保持可用，新 A 会话可以重读原签名 Stage。此前已通过真实单分区 P000/P001/P063/P127 物理闭环。

## 部署 Order/Trade 前的剩余 NO-GO

- 一套**连续真实物理 256 分区**的 A/B Common 集群，必须无手工介入地完成 **128/128** Home 逐分区签名恢复/STRICT READY，统计总耗时、P95/P99、部分完成时剩余正常分区继续客户写入/ACK。现在仅 4 个不同分区分别通过独立单次物理测试，不能把这当 128/128。
- 完整 A down→B 接管→A 追平回 Home→B down→A 接管→B 追平回 Home，期间持续写入并验证无双主、重复执行、错账，真实 256 分区全量 WAL/Custody/业务 Projection 一致。
- 排查本轮 P001 首次 `custody-ledger` 不出现的偶发原因，做持续运行稳定性门禁与性能压力/控制面 CPU 采样。
- 全部 PASS 后，才统一部署带同一版 Common 的 Order/Trade，恢复正式 Robot Maker/Tape 与自动审批/下单/成交/Projection 端到端，验收真实业务 A/B 互切。没有在本轮替换线上 Common 或业务镜像，也没有使用 GitHub Actions。
