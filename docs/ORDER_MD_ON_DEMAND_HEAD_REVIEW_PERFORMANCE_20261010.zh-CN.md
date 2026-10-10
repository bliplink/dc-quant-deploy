# OrderSvr 当前 Checkpoint HEAD 只读预检：低性能开销与安全边界（2026-10-10）

## 代码交付

[OrderSvr commit 5287923](https://github.com/bliplink/com.app.dc.ordersvr/commit/5287923d6ad128bbdff109acbb0c0c853c08d9dc) 新增 `OrderMdCheckpointHeadGate.review(partitionId)`，仅供明确发起的内部安全预检调用，并未注册为 HTTP/Netty 外部 API，也未接入订单、撮合、Robot 或 MD 的逐笔处理路径。

默认配置（缺省即可生效，不需要修改现网文件）：

```properties
order.cluster.mdCheckpointHeadReview.enabled=false
order.cluster.mdCheckpointHeadReview.minIntervalMillis=60000
```

- **默认拒绝和零 hot-path 额外调用**：不启用时 `review` 立即返回 `DISABLED`，不访问任何 Snapshot、WAL、ZooKeeper 或分区屏障。对禁用状态的 100,000 次调用进行了源码级单元回归；这是**功能无 I/O 断言**，并不冒充真实 QPS 基准测试。
- **请求节流**：启用后同一分区至少间隔 60 秒（最低允许 5 秒，低于该阈值直接拒绝）；同一时刻全局只允许一个任务读取快照，其他请求立即返回 `GLOBAL_REVIEW_BUSY`，不排队堆积磁盘 I/O。不存在常驻后台定时任务。
- **低开销检查顺序**：先读取 OrderSvr 已缓存的最新 WAL seq。若落盘快照的 seq 不等于该值，立即返回 `CHECKPOINT_NOT_AT_HEAD`，不生成整份市场摘要；仅当序号一致时调用 `OrderCommitWatermark.hasVerifiedSnapshotBoundary()`，读取最多 64 条快照提交标记附近的 WAL 记录，拒绝有疑义的提交边界；之后在**停写屏障外**构造已持久化市场清单/摘要。
- **极短停写锁区间**：最后通过原有 `OrderPartitionBarrier.quiesce` 进入短暂独占窗口，仅复核 journal `lastSeq`、当前 epoch 和本节点合法 Primary 身份；绝不在屏障内重新读取快照、扫描 WAL、重算完整 Hash。若验证前后 WAL HEAD 变化，返回 `HEAD_OR_EPOCH_CHANGED`。
- **失败即关闭**：缺少集群模式、分区屏障、日志或权威标记、无快照/旧快照/权限变化，均返回明确拒绝状态；无论结果为 `LOCAL_HEAD_CHECKPOINT_MATCHED_ONLY` 与否，始终 `isPromotionAuthorized=false`，证明级别固定为 `LOCAL_VOLATILE_HEAD_OBSERVATION_ONLY`。

## 实测回归

隔离 Maven 全量执行：**311 项，0 failures、0 errors、1 skipped**；新一轮还专门测试了预检期间 WAL 从 `seq=100` 变到 `seq=101` 的竞态，必须返回 `HEAD_OR_EPOCH_CHANGED`，不能伪造成功。测试覆盖禁用路径、请求频控、并发拒绝、短暂屏障内恒定工作量以及晋升默认禁止。构建由 GitHub Actions 跟进。

## 性能和功能边界（必须保留）

该程序仅在手动/内部调用时有工作量，且在热交易路径中没有增加 WAL 扫描或 ZK 请求。读取磁盘快照时仍会消耗短暂的 I/O/CPU，所以默认关闭、有全局并发限制和低频阈值；**未实际模拟 200 租户的极限 TPS，不得宣传没有任何开销**。

该 `HEAD` 只是某一观测瞬间该**本地副本**的 WAL 头与已持久化检查点吻合，既没有独立确认远端的 durable 两副本 ACK、Projection watermark 和另一交易节点，也没有证明所有市场已同步到 MD 的持久化状态。**绝不能单凭这个结果触发 ZooKeeper 主节点 CAS 晋升。** 真正 MD HA 仍需要可信当前源 manifest 签名/鉴权、C learner 追平、两个同步副本、源租约 fencing、旧主归队与隔离故障测试。

当前 10 租户 Demo 不启用该开关、不升级 OrderSvr/MD 节点、不扩大到 25/200 租户或额外故障注入，等待完整 HA 协议通过隔离环境的回归。
