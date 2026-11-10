# 本地源码补齐策略，服务器只编译与回测

## 用户决定与边界

2026-11-10 用户明确：缺少的策略在本机编写和修复，通过本地验证后上传服务器回测、验证；不再使用服务端 DeepSeek 生成策略代码，以节约其 API 额度。此决定不等于停用市场场景分析、现有策略选择或交易风控。

当前可用实盘库存为 4 条，目标 100 条，缺口 96。登记数量、候选数量、编译成功、本地通过和生产发布必须分别统计。不得用更名、不同版本或相邻参数凑齐 100 条，也不得放宽发布门槛。

## 零服务端代码生成链路

`本地源码 → 本地验证段预筛 → 正式 v4 滚动回测＋时序留出期 → 上传固定源码 → INDSvr 编译 → SIMSvr 最近完整 365 天复核 → 现有发布门槛 → 实盘库存核验`

唯一上传入口是 `dc.ind.strategy.candidate.import`，不是 `candidate.generate`。请求必须包含非空场景、完整 Java 源码及固定参数/范围。服务端 `StrategyCandidateImportService` 强制 `provider=external`、`generationEngine=external_java`；`StrategyProvidedSourceDraftService` 直接读取上传内容。已有编译修复路径找不到 external 模型生成器，因此编译失败直接返回，不调用 DeepSeek 修复。页面和台账里的“generation task / generation SUCCESS”是历史任务命名，不代表调用了模型写代码。

提交工具在终态后新增 `source-only-audit.json`：验证 provider、sourceType、generationType、请求及实际 engine 均属于 external import，fallback 为空，并查询该精确策略版本的 `dc.strategy_llm_call_log` 必须为 0；同时保存上传源码 SHA-256 和字节数。出现不符立即停止，不得自动转模型生成。

已核验上一批 `catalog_uniusdt_range_971cc3aa8e74@v1`：external_java，上传源码 33,219 字节，SHA-256 `4e5e07ab70a299b93b55e94069c63482e9c9c382da2983525c14ae1a05477970`，对应版本 LLM 调用记录为 0。服务器自动升级生成开关 `strategy.live.upgrade.auto.enabled=false`；没有为了新候选启用服务器自动生成任务，也没有关闭原来的市场分析。

## 上批完成结果

原后备批次 166/166 完成，无执行错误；本地正式＋留出期通过 1 条（UNI/range），但最近 365 天服务器复核失败：44 笔、PF 2.054659、扣费验证收益 +849.557261、扣费前瞻收益 -872.127642、OOS=0，未发布。生产仍为 4 条合格，缺口 96。

这条失败只作为已观察证据，不调整相同逻辑去重复拟合相同前瞻样本。

## 新的本地 structural_v1 批次

本机 INDSvr 独立工作树：`E:\sourcecode\codex\_work\indsvr-local-structural-strategies-20261110`。只提交测试/研究工具，不合并或部署为生产服务。核心源码、参数和编译类哈希在批次开始前冻结。

10 类结构逻辑，各做多/空一个固定参数版本，共 20 个方向候选：前日成交重心偏离回归、开盘区间双收盘接受、多个完成拍卖区间的平衡突破、前日区间失败接受、双幂变差识别跳跃延续、半方差不对称恢复、成交重心和价格停留分布迁移、位移缺口回踩防守、位移起点防守、连续波动扩张。

所有逻辑只读取当前已完成 K 线及过去数据，适配线上最多 200 根 15 分钟窗口。UTC 拍卖区间必须完整，不用未来/未完成时段补齐；“成交重心”仅由现有 OHLCV 典型价加权近似，不冒充逐笔真实成交分布。固定 ATR 风险参数为 1.5/3.0，目标空间还要求覆盖三倍原有 16bps 执行成本；不按品种调参。

新增 5 项结构策略测试覆盖：20 个唯一方向/10 类、无未来访问、完整历史与滚动 200 根一致、UTC 完整区间约束、成本空间过滤。加原研究 CLI 的 19 项，共 24 项 Java 测试通过。工具侧 20 项 Python 回归通过。

预筛仍只用已约定验证段，不提前读取该批候选的前瞻收益；数据来自既有冻结 READY，不调用 DeepSeek 生成新历史标签。新的结构假设可以按既有协议接受检验，但不能将这些历史留出数据宣传为在所有历史研究中从未观察过。不同类名只是去重初筛，最终计数仍要做逻辑独立性复核。

## 一次执行、断点记录

入口：`recovery/run_local_source_strategy_cycle.py`。它顺序调用本地预筛、正式回测和源码上传/服务器复核工具，没有模型凭据和服务器代码生成入口。SSH 密码只在进程环境内存，不写文件或日志。正式回测串行；SSH 连接启用 keepalive，防止长批次空闲隧道断开。

本次启动：北京时间 **2026-11-10 13:29:55**，启动进程 **8184**。结果根目录：`E:\sourcecode\codex\_work\strategy-local-source-cycle-20261110`。

- 总流程：`cycle-status.json`、`cycle.stdout.log`、`cycle.stderr.log`。
- 验证预筛：`screen/status.json`、`screen/campaign.json`；20 方向 × 10 品种 × 5 场景，共 1,000 个验证项。
- 本地正式及留出：`formal/status.json`、`formal/results.json`。
- 服务器源码与任务：`server/<strategy>/`，必须包含 `source-only-audit.json`。
- 最终生产结果：`formal/cycle-summary.json`、`inventory/summary.json`。流程结束不代表 96 条已补齐，以真实生产资格和逻辑独立性核验为准。

服务端复核范围固定为 `2025-11-10～2026-11-09`。不重测已有失败版本，不篡改已经冻结的参数。若新批次仍不足，继续提出新的独立本地假设或完善所需数据，而不是放宽成本、样本或 OOS 门槛。
