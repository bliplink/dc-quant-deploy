# 集群功能开关与现网验收 — 2026-10-14

范围：Mac mini / Colima Demo，saas-crypto，读取运行中的 Order/Trade/MD 配置及预检。记录源码与运行结果之间的差别，不把配置已开启等同于 HA 已通过。

## 已开启

- Order A/B/C：journal、state、commit、replication、SYNC_PER_RECORD、failover、periodic snapshot 和 snapshot barrier 已开启；三个节点各有 256 份分区 Snapshot。
- Trade A/B：failover、replication、periodic snapshot、recovery source、replica HEAD discovery、stage/install、autoWarm 和 recovery walBatch 均已开启；A/B 各有 256 份分区 Snapshot，但自动预热仍有错误。
- MD-C：本地 ARM64 镜像 dc-saas/mdsvr:cluster-dev-local-mdqa-026306b-20261014。Learner SIGKILL 后恢复 11 个租户行情，角色未变化。
- 已有的 HA 机制不需要为了“全部打开”重复配置或重启。

## 尚不能安全开启

1. MD 自动 Primary 切换：md.cluster.failover.enabled 默认 false。MdAutomaticFailoverService 必须具有生产用的 MdImageRecoveryFailoverController.Safety 实现，包含旧主发布隔离、完整 Order 市场证明和新的 Epoch publishing fence。检查当前源码尚无该生产接线，不能直接改成 true。
2. Order mdCheckpointHeadReview 当前 false：候选 HEAD 观察接口不能冒充持久多副本权威签名证明，而且最新源码尚未替换当前 A/B/C 旧镜像。
3. WAL 物理归档和自动删除：Common 有归档 Ledger、Seal、Retirement 抽象，但运行中的 Order/Trade 未验证到完整业务接线和真实可退休水位。OrderWalArchiveStartupFence 仅在启动时检查 Seal，不负责轮转或授权删除。不可强制删 WAL。
4. Trade recovery.replica.privateDocker.enabled=false 属于实验选项，不等同于正常 A/B 自动预热。
5. MD replayWitness.enabled=false 未证明能完成自动晋升，不应按“全开”直接改动。

## 验收和阻断

- Order A/B/C、Trade A/B、MD A/B/C 容器全部 running、重启数 0。
- MD 256/256 READY，Primary A128/B128，C 为 Learner；只读自动晋升预检维持 BLOCKED。
- OrderB 当前承担全部 256 个 Order Primary；滚动升级预检 BLOCKED，包括磁盘压力、排空、水位、Projection 对账和回滚证明。不能直接重启 B。
- 三个租户 Gateway 公共行情读取/匿名管理接口拒绝回归通过；主站与交易页 HTTPS 200。
- Trade A/B 日志在 08:45–08:46 出现持续的 TRADE_REPLICA_WARM_RETRY（signed-head-manifest，IOException），另有 snapshot is ahead of local journal。Trade 完整灾难恢复不能报为已验收，应先定位真实恢复数据问题。
- Mac mini 系统盘占用约 93%，剩余约 32 GiB；TradeB 数据约 31 GiB。未删除任何当前使用的 WAL、Snapshot 和交易数据。

结论：Order/Trade 核心机制开关已开启。MD 自动主切、WAL 自动退休仍缺生产级真实证明；本轮没有强制打开有数据风险的开关，也没有修改 Gateway 或进行主节点故障注入。
