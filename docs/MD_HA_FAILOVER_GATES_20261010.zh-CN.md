# MD 高可用故障验收门禁（2026-10-10）

## 实盘结果

十租户稳定观察 601 秒、11/11 样本通过；MDSvrB 负责 128 个主分区，进程中断期间 4/10 租户盘口不可用且 Robot 异常。恢复 B 后约 52 秒恢复十租户，之后连续 301 秒、11/11 样本通过。这证明恢复能力，不证明主节点故障下业务持续可用。详见 `TEN_TENANT_MD_PRIMARY_FAULT_OBSERVATION_20261010.zh-CN.md`。

## 自动晋升为何被禁止

ZooKeeper 实机扫描 256 个 MD 分区：A、B 各持 128 个 Primary；全部分区仅有一个指定 Replica，C 并非合法同步副本。通用 PartitionFailoverController 需要晋升后保留同步副本，还需要控制面租约、CAS fencing、候选同步进度证明。现有 MD 业务尚未实现独立的 durable market watermark、promotion safety proof 及完整 epoch 快照晋升协议。因此 ZK 的 READY 不足以授权自动晋升。

只读脚本 `scripts/check-md-failover-preflight.py` 将这些事实转换为机器可读的 BLOCKED 结果。无论分配是否已有两个 replica，它都禁止将静态信息当作安全晋升证明。所有操作仅查询 ZooKeeper 分配与 Docker 镜像，不修改现网。6 项测试覆盖真实拓扑、即使具备多个副本仍不能伪造证明、错误状态和异常节点。

## 已提交的基础机制

MDSvr `1b2ed12` 增加只读路由随角色和 epoch 变更的后台对账：旧 Primary 丧失权限时撤销对应 PartitionReadinessGuard；新 Primary 的合法只读路由建立在当前 assignment epoch，发布行情仍须先获得完整市场快照。共 48 项 Maven 单元测试通过。该补丁未加入 ZK 自动晋升，也未验证跨节点复制。

## 真正解决 P0 的顺序

1. 扩展为三节点真实同步复制；每分区需要两个经过完整 OrderSvr 行情快照、连续事件和 freshness watermark 验证的合法 Replica。不可把 C 的进程存活等同于同步完成。
2. 构建唯一领导者 ZK 控制器、主节点失联检测、基于已同步状态的 candidate proof、带版本 CAS epoch 晋升和过期主节点发布栅栏。控制面断开必须拒绝写入和过期行情发布。
3. 晋升时基于权威完整市场快照重新开放 publish；Robot 只有在 OrderSvr 挂单与账户/持仓核对后才能恢复，严禁重复单。
4. 隔离环境运行持续十租户流量下的故障注入、旧主归队、角色反转、双主检测与持久化成交/账户对账；通过后再进行 Mac 受控故障注入。当前不扩大到 25 租户，不继续触碰 Order/Trade 主节点。

## 适用范围

这是安全机制和可读门禁，并非完整的自动 MD 主故障接管。待真实晋升协议及其测试完成，才可将 P0 由未通过改为已通过。
