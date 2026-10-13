# 2026-10-14 Mac mini / Colima 磁盘与虚拟机恢复记录

## 事件与确认的事实

MD HA 开发时本地 Maven Docker 测试无输出，Docker inspect 与本地 Gateway 超时。Mac mini 的 APFS Data 卷剩余仅约 178 MiB，系统盘显示 100% 已用。Colima 的 Lima VZ 日志持续报告 "Invalid virtual machine state. The virtual machine is no longer valid." Colima 状态错误不是 Order/Trade/MD 应用自身的故障证明。

**不能确定磁盘耗尽是否直接引起 VZ 虚拟机失效**；两者同时出现，因此统一作为宿主机稳定性事件处理。Colima 旧实例和虚拟磁盘必须保留，不能删除数据后重装。

## 已执行的恢复动作（没有删除业务数据）

1. 删除已完成 Docker load 的两份临时 GHCR ARM64 传输 tar（约 428 MiB）。
2. 清除可重建的 uv/Python 缓存、旧隔离 Maven 仓库和早期 Maven CI 缓存，不触碰源码和验收日志。
3. 在 2026-10-12 的旧 HA 验证源树中，只删除 **20 个 target 目录**（共约 3.64 GiB），保留原源码、WAL 封存测试证据和归档 gap fixture。
4. 确认当前运行目录为 ~/.opentradingcore/dc-saas-runtime-epochwarm20261013，全部 data、log、control 均未清理。
5. 既有 Colima VZ 已无有效 Guest，依次使用 colima stop --force 和 colima start 恢复同一虚拟机。没有执行 colima delete / Docker prune / 卷删除 / Compose down -v。
6. 恢复后系统盘可用空间约 39 GiB（91% 已用）。Colima Docker Engine 29.5.2 恢复，24 个业务与基础设施容器运行。

## 恢复验证

- MySQL：11 个租户、48 个用户，原始数据保留。
- ZooKeeper：MD A/B/C 临时成员均有效。
- MD：256/256 分区 READY；MDSvrA Primary 128 / MDSvrB Primary 128，MDSvrC 仍为 Learner。
- Order A/B/C、Trade A/B、MD A/B/C、Gateway：状态 running，重启次数 0。
- 主站与交易终端 HTTPS 200。
- 三个租户的只读 Gateway 公共接口通过；匿名管理接口拒绝符合预期。
- MD 自动晋升仍有五项安全阻断，不允许 MD Primary SIGKILL。

## 预防性措施

MD HA 的只读预检现在检查宿主机可用空间；少于 5 GiB 时添加 HOST_DISK_RESERVE_BELOW_5G 阻断。此阈值仅供 **HA 故障注入前检查**，不是长期运维磁盘容量目标。继续完善日志归档、Snapshot 保留策略与可用空间告警时，应避免逐笔交易热路径磁盘扫描、全局 IO 和大文件反复遍历。

未在本事件中启用或测试 MD 自动主切；不得把 VM 恢复当作 MD HA 故障切换验收。
