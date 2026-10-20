# Common 同 Key 并发队列缺陷修复交接（2026-10-20）

## 修复位置和合并入口

- Common 仓库独立 worktree：`.work/app-common-queue-fix-20261020`
- 独立分支：`fix/common-single-key-worker-20261020`
- **已提交修复**：`b0be90c` — `fix(common): enforce atomic per-key worker admission and queued-tail recovery`
- 修改文件：
  - `src/main/java/com/app/common/thread/AsyncSingleSeqThreadGroup.java`
  - `src/test/java/com/app/common/thread/AsyncSingleSeqThreadGroupConcurrencyTest.java`
  - `docs/COMMON_SINGLE_KEY_QUEUE_FIX_20261020.md`

当前其他 Codex 会话验证的 Common HA 分支**没有被覆盖或合并**。待 HA 工作准备合并时，在其确认可合并的 Common 分支执行 `git cherry-pick b0be90c`，如有同文件冲突，保留最终的按 Key 原子 Worker 创建/入队语义，并重新运行 Common 与订单撮合回归。

## 已确认根因

运行中的 Common 3.0.22 `AsyncSingleSeqThreadGroup` 在 `get()` 返回 null 后，使用 `synchronized(className + id.intern())`，但拼接字符串不是同一个锁对象，且锁内未重新读取 `ConcurrentHashMap`。多线程可以为同一 key 创建多个物理 Worker，导致原本应串行的订单处理并行。

直接运行部署中的 Common JAR，16 并发初次提交同一个 Key，**最大同时处理 16**；叠加修复后的 class，连续 8 次测试同样 16 个提交，**最大同时处理均为 1**，全部完成。

## 修复与验收

- `ConcurrentHashMap.compute` 原子执行该 Key 的 Worker 初始化、失效替换和队列入队；不同 Key 仍允许并行。
- 死 Worker 的**未消费队列**转移到新 Worker，并先于新提交入队；已经进入处理中的业务事件不能直接重放，仍依赖业务 WAL/日志对账。
- `dispose` 同提交采用读写锁互斥，关闭后拒绝新提交。
- Java 8 编译通过；新增并发测试 7 项、已有 `AsyncCacheBaseRaceTest` 1 项，合计 **8/8 通过**。
- 测试涵盖 16、32、100 线程的同 Key 初次提交、10,000 事件无重复无丢失、跨 Key 并发、死 Worker 后待办转移、并发恢复与关闭后拒收。

**本次仅隔离源码修复、编译及测试：没有替换 Demo 上运行中的 Common/Order/Trade 容器，也没有发布 Maven 中央仓库版本。** 合并后应以相同 Common 版本本地统一编译，最后做真实两个交易员同时下单撮合、成交和资金持仓对账。
