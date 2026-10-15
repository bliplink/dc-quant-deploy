# Mac Trade P190/P220 已提交 WAL 原始记录核验｜2026-10-15

**仅限只读取证：不签发 READY、不安装 Replica、不删除 WAL、不宣称生产 Quorum。**

在 Demo `dc-saas-runtime-ordered-20261015` 上，P190/P220 同 Epoch 主副本 WAL 的最后已提交记录在物理原始 Chronicle 编码文本层面逐条一致，但下一个未提交 WAL seq 已分叉。为避免依赖日志肉眼比对，增加可重复执行的 `tests/audit_trade_committed_prefix_readonly.py`。

### 执行方式

```bash
python3 tests/audit_trade_committed_prefix_readonly.py \
  --data-root "$HOME/.opentradingcore/dc-saas-runtime-ordered-20261015/data" \
  --partitions P190 P220 \
  --output "$HOME/.opentradingcore/otc-demo-direct-20261015/acceptance-evidence/committed-prefix-readonly-20261015.json"
```

输出路径必须不在真实数据根目录下且不存在；不打印资金、密钥或原始事件 payload。源端要求 Snapshot 分区、Epoch、snapshotSeq、committedStateSeq 和持久化 baseline 一致，并核验 `STATE_COMMIT` 与前一条 `STATE_BATCH` 对应。取原有归档 segment 的顺序连续 1..N 记录，与 Replica 当前 `.cq4` 记录逐条 SHA-256 核对，任何遗漏或内容分叉均不允许报告“前缀相同”。CQ 是二进制文件，脚本以 JSON 编码包络验证定位，不把紧随包络的二进制字节当作文本内容。

### 本机结果（不含认证授权）

| 分区 | 已提交 marker | state seq | 核验记录 | 原始记录的双端结果 |
|---|---:|---:|---:|---|
| P190 | 13916 | 13915 | 13916 | 完整一致 |
| P220 | 12468 | 12467 | 12468 | 完整一致 |

P190 提交前缀链摘要：`b2a331d20f70f1528128f32659ef077210145d2a3f4cc460ff0e5c09286d95c5`。P220 前缀链摘要：`96ba2f10607efdbebce53e7f52f14039c461767c2c2db45d089650b27cf00ff3`。合计 28,384 条编码记录检查通过，源 Snapshot SHA 分别为 `f627c296c9d05a0e195ede06b6038c464ee2baff40c23fe623d34224ef83ed61` 与 `a46480c138effc44d06ad7209ac30c153138d11ad00b1cfc6ba05cb8864c3766`。

脚本强制在报告中设置 `signedSourceHeadVerified=false`、`independentPhysicalQuorumVerified=false`、`authorizesReady=false`、`authorizesReplicaInstall=false`、`authorizesWalDeletion=false`。**这些摘要是来源归档和副本日志可恢复性的排查线索，绝非独立签名承诺或 WAL/CQ 文件的完整二进制格式证明。** 还缺 Common 的可信源 HEAD、整个原始 WAL 区间、多物理节点独立签名、接收端持久恢复事务，以及资金/持仓/委托/成交/Projection 外部权威对账。

配套五项合成回归测试：前缀完整且仅未提交尾部冲突可以作为只读证据；已提交记录不一致、Replica 丢记录、快照提交边界错配、非法 partition 均 fail-closed。**本工具不得连接到任何自动主切、Replica 安装或 READY 业务代码。**
