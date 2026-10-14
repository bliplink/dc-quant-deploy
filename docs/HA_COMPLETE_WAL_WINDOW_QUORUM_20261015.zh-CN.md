# Common/Trade 可信 WAL 全区间认证与资源预检 — 2026-10-15

## 架构边界

本次继续遵循：Order/Trade 的签名协议、独立副本凭据、Journal 状态机恢复协调器归 Common；Trade **只**实现 Chronicle 原始字节和累计 Trade STATE_COMMIT 的业务适配；Gateway 不参与业务恢复。MD 后续需要借用相同 Common 接口并提供自身市场 Snapshot/Diff 和旧发布者 fencing。

先前 [Common Draft #15](https://github.com/bliplink/com.app.common/pull/15) 和 [Trade Draft #16](https://github.com/bliplink/com.app.dc.tradesvr/pull/16) 已能分别认证物理投票节点、ZK 版本、epoch、STATE_COMMIT 原始物理标记 SHA 和累计状态。**缺口**：相同的最终 STATE_COMMIT 不一定说明中间所有 STATE_BATCH 内容相同，尤其是在日志已经归档或发生局部分歧时。

## 本轮候选改动

- [Common Draft PR #21](https://github.com/bliplink/com.app.common/pull/21)：`RecoveryWalWindowDigest` 使用独立域分隔的 SHA-256，对 **签名 Snapshot 基线序号之后**至权威 committed HEAD 的原始 WAL 字节逐条做长度分隔哈希。完整性要求：同一分区、epoch，所有序号无缺口、无重复、无越界，最多 4096 条、64 MiB；不能读到真实历史日志时拒绝而不是猜测。投票凭据改成**新 v2**，绑定 Snapshot SHA256、窗口起点、终点、WAL 区间 SHA256、STATE_COMMIT 标记 SHA256、累计状态 seq/epoch、物理节点、ZK 版本和新挑战。旧 v1 仅签提交标记的凭据不能被当作 v2。
- [Trade Draft PR #22](https://github.com/bliplink/com.app.dc.tradesvr/pull/22)：`TradePartitionJournal.replayRawRecoveryWindow` 以原始 Chronicle 文本读取活跃 CQ 和留存的 Archive 段，不先解码再编码成新的记录；业务适配器在排他 Trade 分区屏障及真实 ZK 角色检查内，先同步至指定提交标记，验证累计 STATE_COMMIT，然后逐条读取原始物理 WAL 帧、校验 Trade 事件合法性，交由 Common 生成区间摘要。Archive 缺失、WAL 序号断档、同序号但字节变化，不能获得完整摘要。
- 负向测试：同一最终 STATE_COMMIT 和累计水位，两个真实 Chronicle 实例仅中间 STATE_BATCH 原始内容不同，完整窗口 SHA 必须不同；漏掉任何一个物理槽不得通过；错误 epoch、分区、Snapshot SHA、ZK 版本、投票身份或密钥都拒绝。

## 验证与现网事实

- **候选 CI**：Common [Actions 38644610494](https://github.com/bliplink/com.app.common/actions/runs/38644610494) 已通过。Trade [Actions 38645122275](https://github.com/bliplink/com.app.dc.tradesvr/actions/runs/38645122275) 的最终结果应以 GitHub 真实状态为准，不能用先前的旧版本构建冒充这一轮测试。
- 所有变更仍在 **Draft/候选分支**；未合并到主发布的 `saas-crypto`、未发布 Common Maven Central/GHCR，也未替换演示服务的 Order/Trade 镜像。
- **2026-10-15 06:03–06:xx CST** 只读检查：现役 24 个 SaaS 容器，Robot `11/11 RUNNING`、活动挂单 440；宿主机磁盘使用率约 69%、可用约 135 GiB。Colima 8 CPU/16 GiB RAM，旧 1 GiB Swap 约已用满，但 `MemAvailable` 约 6 GiB 且采样 `vmstat` 无持续 `si/so`，不可将 Swap 已占满直接判断为正在抖动。
- 追加 2 GiB `/swapfile-extra-2g`，权限 `0600`，在线 `mkswap/swapon`，仅追加唯一 `/etc/fstab` 启动项，**无 Docker/服务重启**。更新后 SwapTotal ≈3 GiB、SwapFree ≈2 GiB，Colima 根分区剩余约 15 GiB；重启持久化尚未实测。
- 再执行正式 `tests/order_ha_rollout_gate.py --target OrderSvrA`：`NO-GO` 仅剩两个真实负载条件：`50/50 RUNNING`、2000 活动挂单。**不可跳过**，也不能以 11 户的存活等同于 50/200 户容量验证。

## 未通过的 HA 安全门槛（P0）

1. 生产接收端必须实际调用 Common quorum verifier，从独立且可信的 ZK 投票成员和**每节点独立密钥**获取同一 Snapshot+WAL 窗口认证，而不是测试里构造的凭据；要求在镜像安装、日志导入与 READY 前后重新校验 assignment / source HEAD。
2. 这次窗口上限 4096/64MiB，若快照基线较老，必须先走安全的 Snapshot 刷新或多段链式校验，不能默默截断窗口；未留存完整 WAL 归档时坚决拒绝签字。
3. 长窗口扫描目前可能在 Trade 分区业务屏障内产生可感知 I/O 和延迟，**启用前必须压测并收紧锁占用/扫描预算**；正常下单性能优先。所有恢复接口默认关闭。
4. 真正的 HA 还需财务/持仓/委托/成交/Projection 的权威一致性检查、MD Snapshot/Diff 及旧发布者隔离，50/200 租户性能、真实 SIGKILL、主备反转和跨物理节点验证。所有候选代码的 Java/Docker CI 成功都不代表 HA failover PASS。

**许可结论：继续开发与只读审计；NO-GO 上线新版镜像、直接主节点 SIGKILL、提前清除不可证明的 WAL 数据。**
