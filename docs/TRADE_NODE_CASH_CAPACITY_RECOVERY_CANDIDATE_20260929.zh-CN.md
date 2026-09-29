# Trade 整节点现金索引容量与冷恢复候选验收

日期：2026-09-29。Trade 本地提交 `a539940d4b83a1010096b8efae68adce56917b8c`，接续混合覆盖候选 `d934291`。**显式隔离候选，未接线上启动/业务入口，未部署或压测。**

## 本轮补上的缺口

单分区现金索引恢复成功不能证明整个节点有容量：尚未恢复的分区、副本和 learner 可能仍有已提交的原结果记录。分别能放下的两个分区，合起来可能越过节点上限。新候选因此默认关闭新现金 admission，必须先完成整节点本地文件清点与恢复证明，不能把“还没加载”当成“没有历史”。

`TradeCashNodeRecoveryCandidate` 无自动 bean，是有界停机维护原语，不是已接入的生产恢复调度器。它要求严格状态/复制/commit/lifecycle 配置、控制面连接，以及同一组 runtime/coordinator/journal/watermark/planner/authoritative applier/ledger；不能从已持有的业务分区屏障内启动。

## 执行与失败边界

1. 先关新现金门禁，取得独占私有 token；活动未确定结束的 reservation 阻止恢复，不确定 reservation 不丢弃。
2. 从 runtime 取得完整服务 assignment 清单，核对数量、唯一规范 ID 和逐项路由视图；本机 primary、replica、learner 全部纳入并 fence。不是调用方任选一组主分区。
3. 使用实际恢复 planner/applier 对每个本地 snapshot＋committed delta 预验证，未安装任何余额。缺基线或 dirty tail 拒绝，不能查 SQL 或生成伪空历史补齐。
4. 合并全部现金原结果镜像，跨分区重复身份和总条数/字节超限先拒绝；保留的非本机记录与 pending 占位也计入。首次安装业务状态前必须证明总容量能容纳。
5. 按固定顺序持有所有 resident 分区屏障，复核完整归属及 journal 坐标后安装；全部业务 callback 成功后才替换索引。部分安装异常 fence，不回滚已提交资金、不截断日志。
6. 推进精确 coverage，关闭所有输入并再次复核后，才能打开节点现金门禁。关闭失败也不开放。**不自动 mark READY、不 promotion，不代替副本 catch-up/提交来源证明。**

完整归属元数据改变或控制面断连会把新现金门禁锁闭；仅重新连接或把元数据改回去不能重开，须再做整节点恢复。单分区 restore/低层 index install 会取消整节点证明。原结果 retry 仍可在原有身份、primary/READY 和精确分区 coverage 合格时返回原结果，不重新计算或占新容量；恢复期间 resident READY 已撤销。

源对象/严格配置/屏障等前置拒绝发生在新 session 开始前，不会误取消既有有效证明；session 开始后的失败才保持新现金门禁关闭。旧/外来 token 不能结束或取消别的恢复。

## 快照与资源限制

- snapshot 必须精确匹配其 journal committed prefix 的 marker/stateSeq/stateEpoch。旧 v2 snapshot 没有现金 manifest，必须只读扫描其已覆盖前缀；前缀出现 v2 现金/现金结果时拒绝，不能默认为现金记录数零。不自动修改旧快照。
- v3 count/digest manifest 用于发现意外损坏/遗漏，不抵抗被同时恶意重写的 manifest，不代替账务对账或完整 v3 前缀重建。
- 服务清单上限 4,096，本机 resident 上限 256；256 层屏障边界用**真正全新合成分区**的空快照验证，257 在打开文件前拒绝。这不授权给现有生产分区造空快照。
- 索引上限仍为每节点 10,000 条、16 MiB 序列化数据、单条 64 KiB；这是索引协议上限，不是 heap 配额，不覆盖全部余额/持仓/去重对象。
- 准备期持有全部 snapshot/输入资源；真实大分区的内存、文件句柄、IO、GC 和恢复耗时未验收。每笔新现金复核完整清单为 O(服务分区数)，其 TPS 开销未测。
- 归属复核是 cached runtime 视图，不是 ZooKeeper 全局原子 CAS、租约或 quorum。普通逐分区恢复会取消节点证明，启动/角色变更/有界调度接线仍待完成。

## 本轮验证证据

- Trade：Java 8、缓存依赖、断网执行，最终 **66 类 / 349 项，完整两轮**通过，零失败/错误/跳过。新增节点门禁 29 项；覆盖条数/字节合并超限、primary/replica/learner、完整清单异常、归属/尾变化、并发 admission、reservation/token、失败安装/资源关闭、snapshot/mixed delta、旧快照隐匿现金和 256/257 边界。
- Projection：源码保持 `3122a8d0ab94d5e7a4e177951b2e4ed5ee58d38d`，**12 类 / 73 项**通过；使用最终实际 Trade producer/result classes 的 **45 项隔离 MySQL 一轮**通过。不要与上一消费者切片 45 项×3 轮相加为本轮成绩。
- 实际互通报告保存在本地 Projection `target/trade-projection-offline.osJtUJqz/result.json`；SHA-256 `922742156f42924d1aec362e7bac28276d4a8cc0f51fb34b9105dbc6464654f8`。数据库仅为独立合成 tmpfs 实验，无 host port/运行数据挂载；临时容器已回收。
- 2026-09-29 **10:03:21 UTC** 只读核对：Order A/B、Trade A/B、MD A/B/C、Projection 共 8 容器运行，restart=0、OOM=false，仍为原镜像。该检查只证明进程状态，未重新测试业务可写或读取风险触发型业务 API。
- [结构化证据](evidence/trade-node-cash-capacity-recovery-candidate-20260929.json) 保存提交、class/report 摘要、范围与未验收项；无认证信息。

## 下一步仍按底座优先

1. 用已有隔离大分区副本验证 prepare/install 的峰值 heap、句柄/IO、GC、阶段时长和完整状态摘要，再制定整节点预算；B 的 384 MiB 大分区接管门禁仍未通过，不能由 256 个合成空分区推导。
2. 把有界恢复执行器与 Order/Trade/MD 的实际生命周期 adapter 接通，验证取消/角色改变/资源关闭及 catch-up/READY；不能把这个停机原语直接接作生产启动循环。
3. 补真实全部业务后态 adapter、可信历史/配置基线、原结果冷留存/投递 GAP、资金费/保险/ADL。SQL Projection 不作为核心恢复来源，旧 SQL-first writer 仍未退场。
4. 之后做隔离故障、业务重试/账务与 MD 序列核对，再按 300/16 逐级量测成功业务 TPS、故障降级容量和 RTO/RPO。

本轮没有线上现金交易、admission/撮合负载、故障注入、重启、assignment/SQL schema/历史修改、镜像推送或发布；不宣布全节点 heap 容量、财务正确性、HA 或 TPS 已通过。
