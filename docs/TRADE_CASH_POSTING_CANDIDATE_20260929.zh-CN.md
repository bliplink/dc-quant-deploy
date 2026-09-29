# 现金与不可变流水：候选事件及隔离验证

日期：2026-09-29。本轮仍以集群底座安全为目标，补故障恢复前需要的资金事件完整性，不做线上现金操作、历史修复或 TPS 测量。

源码已本地提交：Trade `360bda1`（事件构造/恢复校验）及 `62615ef`（服务端账户模式绑定）；Projection `dcf26b1`（默认关闭的流水物化）。没有发布 Common、推送/部署服务镜像、改变 assignment、开启物化、停止原 DAO 写入或重启运行服务。

## 本轮已经验证的范围

- 纯 `TradeCashStateBatchBuilder` 接收显式客户端操作 ID、服务端已计算的余额前/后态、方向及首次接受时间。将余额和完整 POSTING 放入同一 STATE_BATCH，冻结输入对象；不调用 DAO、业务入口、网络、安装、提交或发布。
- 检查现金余额的有符号差额、保证金/冻结/状态未夹带无关变化、必要的可用余额约束、数字/字段范围及有效时间。仍须调用方完成既有未实现盈亏、账户权限、产品币种等完整风险准入；这不是交易计算/多币种账户引擎替代品。
- 稳定流水 ID 为版本化的 location/user/client-operation-ID 长度前缀 tuple 的 SHA-256。不使用钟表、节点、epoch、随机 eventId 或金额当操作身份；方向不进入 ID，所以同一请求改方向/金额仍是同 ID 冲突。金额沿旧现金计算绝对值语义归一，流水正金额配 type=1/2 表示方向；不改旧路径和历史流水。
- 请求指纹覆盖归一金额、方向和账户/币种/产品/附加信息，不覆盖当前余额或时钟。流水账户模式来自服务端余额，矛盾的请求标签被拒绝。指纹为后续核心持久去重准备，**当前没有请求去重状态机**。
- POSTING 恢复不安装历史流水 map，但会在全量预验证阶段检查不可变操作、tenant/user/id 对应、金额与时间等字段，坏流水不得只恢复余额后标记 recovered。合成真实 Chronicle 日志已验证有效批次反复恢复不重做现金计算，以及坏流水/未提交状态不改原余额、不标记 recovered。
- Projection `projection.trade.postingTable.enabled=false` 为默认值；启用必须同时启用 core table materialization。检查流水表 InnoDB/完整唯一键；原始金额/首次时间/账户币种等参数化 INSERT 与余额、归档、watermark 共用一个事务。info/demo/请求指纹等未有对应查询列的内容保留在完整 mutation 归档，不虚构字段映射。
- 重复传输在同一已提交坐标由 watermark 跳过。同一流水 ID 出现在**另一提交坐标**，无论内容是否相同，都拒绝完整事务，不使用 INSERT IGNORE/REPLACE/覆盖更新隐藏冲突。它只能检测投影端重复资金效果，不能反向修复已经错误提交的核心余额。

## 证据与复现

Trade 全量：60 个类 / 242 用例，新增 20 个候选/恢复用例。Projection 全量：11 类 / 56 用例。最终候选实际 class 组合的 MySQL 8.0.36 **26 项隔离用例连续 3 轮通过**。机器可读记录见 [证据](evidence/trade-cash-posting-candidate-20260929.json)。

Projection 标准隔离脚本只用该模块时有 25 项；预先编译 Trade 后，设置 `DC_PROJECTION_TRADE_CASH_CLASSES=/absolute/tradesvr/target/classes`，再运行 `bash scripts/run-trade-projection-mysql-offline.sh` 增加实际构造器 payload → SQL 一项，共 26 项。仅挂载编译类只读目录，不挂载 Trade 配置/数据/日志，不启动 Spring 或 facade。使用本轮同一套 common 3.0.14/bridge 摘要，没有混用通用恢复执行器的另一个构建。

MySQL 无外网/宿主机端口/线上挂载，只有合成数据和 tmpfs，按准确容器 ID 与 ownership label 清理。坏引擎测试曾被 MyISAM 的 UTF-8 索引长度限制挡住；改为先对**全 ASCII 的临时测试表**转换字符集再注入坏引擎，验证后恢复。没有对线上表执行相应 DDL。临时数据库已删除，JSON/依赖副本保留。

只读运行容器核查：Order A/B、Trade A/B、MD A/B/C、Projection 共 8 个容器仍为既有镜像，running、restart=0、OOM=false；这不是业务可写、跨宿主机 HA 或 RPO 证明。

## 接入前不能跳过的门禁

1. 引入明确的现金 API 操作 ID 与已认证租户/用户绑定。没有操作 ID 的旧接口不能被偷偷赋随机 ID 后宣称重试幂等；session/transport ID 也不能代替业务操作 ID。
2. 核心记录请求指纹与首次完整结果，提交前查重：同 ID/同内容返回原结果，同 ID/不同内容在资金效果前拒绝，不用当前余额拼出“原结果”。请求结果与余额/流水作为同一权威提交单元。
3. 将现金去重状态接入完整日志、快照、恢复预验证和 epoch fencing；定义容量/保留/重试窗口，不能随意淘汰旧 ID 后允许再次入账。不要直接复用可能淘汰条目的执行缓存来冒充持久去重。
4. 验证先计算待提交后态 → 本地/副本提交证明 → 安装/发布/成功响应的崩溃窗口。不能先调用旧 `wdBalance` 的 SQL/发布路径，再把候选批次补写到日志后宣称原子性。
5. 定义不可变流水的本地历史留存/归档与 Projection 可重建起点；当前 runtime snapshot 不保存完整 posting 历史。不能修剪唯一的权威历史，再只靠数据库投影反向恢复。
6. 做可信历史基线、全表对账与旧 SQL 写入方退场，再逐服务统一版本/存储兼容门禁。新严格 POSTING 格式未做全量历史兼容审计；funding、保险和 ADL 路径仍须分别迁移。

因此旧现金 handler/facade/recorder 的业务行为未改，本轮不能宣称“现金已保证重试不重复”“核心已彻底不写 SQL”“异常切换/TPS 已验收”。下一步优先补原结果持久去重和快照恢复，再接入隔离现金请求崩溃/重试演练；总体顺序仍按 [集群底座计划](REUSABLE_CLUSTER_FOUNDATION_PLAN_20260929.zh-CN.md)。
