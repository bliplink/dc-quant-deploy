# 原机制全目录：固定 ATR 退出研究

用户已明确确认：继续只用现有 OHLCV 研究，不改服务架构。本批及接续均不得扩大到资金费率、持仓量等新因子或相关服务改造；不因该限制放宽资格门槛。

## 范围冻结（金融验证前）

前一个正式口径标签批次 28444 已结束：20 个源码/信号合同通过，1,000 项初筛 0 通过，0 上传/发布；16:34:18 北京时间库存仍为 4、缺 96，最终证据 `strategy-formal-payoff-cycle-20261110/formal/cycle-summary.json`。模型及失败记录冻结，不再改变接受阈值重试。

本批不再给原 10 种事件更换估计器。取此前 `strategy-95-campaign-20261110/catalog.tsv` 的完整目录，211 个原入场类、418 个实际方向组合，目录 SHA256=`0eacf30330d033a9fd1d43ee0789f075898554fd8170d7554155bf0eef9457d2`。不按已看到的财务收益挑参数或机制；逐项保留原目录第一次声明的参数、方向、40～200 根预热、入场条件、原止损和原止盈。

只给新候选加入同一已冻结保护策略：入场 ATR20 对应首阶 max(.5%,2ATR)、步阶 .5ATR、正的保底触发=首阶+步阶/保底保护=首阶-步阶；整个持仓使用入场时冻结的值。首阶遵守现有 EMS 下限，不改用户设置或生产服务。它与旧固定 .5/.2% 退出有不同实际管理语义，但旧机制及新退出版本不能同时算两条独立策略填同一缺口。

原类拷贝为 `CatalogAtrExit*`，原 setup 改为内部原入场函数再封装退出；4 个继承父类 setup 的过滤类明确调用 super.setup，保留原过滤器。导出仍只嵌入被选中的实现及依赖，不生成服务器代码。新 cohort=`catalog_atr_exit_v1`；canonical all 必须包含全部新名称。

## 验证与成本控制

测试逐项反射恢复原构造参数，核对 418 组标量参数、原入场出现/不出现、方向/entry/stop/take、四个保护字段和有实际信号的人工数据；另外检查未来数据访问与 200 根窗口一致性。与已有回归一同构建，不能在同一工作树重叠 Maven。

全流程为 418 个源码合同/固定验证月逐信号一致性 → 20,900 项不读留出的验证 → 既定单元缺口及机制去重 → 正式 v4 与时序留出 → 合格固定源码外部导入 → 服务器 365 天回测与发布/库存审计。所有成本、样本、PF、回撤、场景、OOS、前瞻贡献及基线门槛不变。任何预筛通过数不代表正式合格或上线。

本机源码检查增加显式 `--workers 2` 上限：两个独立产物目录、独立 JVM，按原目录顺序由主线程写聚合账本；任一失败不写 SOURCE_CONTRACT_COMPLETE。原默认仍为 1。仅降低串行启动耗时，不跳过编译、服务端合同或逐信号比较。服务器生成/修复代码继续禁用，不扩大到新因子采集或运行时架构。

## 构建及执行接续

86 项 Java 回归测试、84 项 Python 测试通过。本地研究提交 64b7bed17c93352209de92a3f281beb7e59da55b，远端独立研究分支 `codex/local-catalog-atr-exit-strategies-20261110` 提交 17d0600142847906df251d21b84faf5a6a881096；核心与测试文件 blob 已逐项核对。没有修改或发布生产服务镜像。

北京时间 16:40:26 以 PID 18140 启动完整流程，输出 `strategy-catalog-atr-exit-cycle-20261110`，最近服务器窗口仍为 2025-11-10 至 2026-11-09。418 项源码检查需要一定时间，以实际 source-contract/status.json、cycle-status.json 及子进程为准；不要仅因尚无新实盘数量就重跑已经完成的财务结果或修改被冻结源码。

18140 在第 67 项源码合同失败，已结束且未进入任何财务初筛/留出，前 66 项通过证据保留。错误为 ADX-like 过滤合同未实现，而非已完成财务亏损。额外只读诊断在一个独立 JVM 调用未经修改的正式 StrategyGeneratedSourceValidator，对全部 418 份固定源码检查：414 通过，4 失败；证据 `strategy-catalog-atr-exit-source-rules-audit-20261110/audit.json`。此诊断不代替单份编译或逐信号检查。

4 项失败是 AdxDirectionalBreakoutHypothesis、SelectiveAdxBreakoutHypothesis 的多空各一项。核对旧代码为方向运动/强度代理，不是完整 Wilder ADX；不添加未使用的 isStrongTrend 假方法，不改名避开校验器，不给校验器例外。将这 4 个明确标为 INVALID_SOURCE_CONTRACT，从新研究资格目录排除；保留原类和失败证据，未声称已修复它们或把它们算作合格。

剩余 209 个原类、414 个方向的参数/入场/原风险/保护均保持不变，在新目录重新冻结并完成全部 414 项单份编译/合同/逐信号验证，然后进行 20,700 项初筛及后续原正式流程。更改只发生在财务前的源码资格目录，任何源码失败项都不进入金融筛选，原失败目录不覆盖。

资格目录修正后 86 项 Java 再次通过，Python（含语义审计和并行合同）89 项通过。本地研究最终 d72ee16cdebcc24b095698930ae13e0369726042，远端同一独立分支最终 ad313c0a6ee1076f80d34638e3aa4ed512f7dd60，两个变更 Java blob 已核对一致。16:55:13 以 21056 启动新目录 `strategy-catalog-atr-exit-cycle-20261110-sourceeligible`，之后以这个进程/账本为准。旧首轮 18140 已结束。批量源码规则诊断工具只是提早报告所有规则失败，未替代新目录中每一项实际编译、合同和逐信号检查。

## 发布前必须落实机制独立性复核

17:32 左右完成全部 414/414 单份编译、未经修改的生产源码合同和逐字段信号一致性检查；17:39 完成全部 20,700 项验证初筛，303 项预筛通过，按原缺口/每类一次规则选出 51 项。campaign SHA256=`01d579530f1adca4194270f311db9075baf39469035dd262e42647fa712e880f`。随后进入正式 v4/独立时序留出；17:44:47 已完成 9/51，正式合格 0、执行错误 0。初筛通过数不是实盘数量，正式最终结果应继续读取 formal/status.json 和 cycle-summary.json，不把此中途快照当作终局。

17:38:57 北京时间（09:38:57 UTC），通过只读 live.strategy.backup.export 获取当前 4 条 ACTIVE 的精确 name@version 源码，私有证据保存在 `strategy-active-peer-source-review-20261110-1739/manifest.json`，不放入公共仓库。工具为 `recovery/export_active_peer_review.py`；未变更注册表、订单、持仓、风控或调用代码生成。比较时使用该备份的精确版本，不使用旧 100 条 seed 冒充当前库存。

原 shortlisted 记录要求语义复核，不能只按 Java 类名不同自动当作两个独立机制。CatalogAtrExit 候选现在必须有 `formal/semantic-review.json` 才能进入服务器导入；缺少、未批准或证据不匹配只标为 deferred，不把财务合格改成财务失败，也不调用服务器生成器。

schema 为 `independent_mechanism_review_v1`，reviews 每项包含 strategy、source_sha256、symbol、scene、decision=APPROVE、mechanism_id、reviewer、rationale、active_peers 和 peer_comparisons。复核必须绑定本地通过的源 SHA/范围，明确比对该单元当前每一个 ACTIVE 合格版本（name@version）及其入场机制；同单元本批多个候选的同一 mechanism_id 最多一个进入导入。不能为增加数量给克隆任意起不同机制名。

复核由当前本地开发会话在读完正式结果和固定源码后完成，不需要用户逐条操作；不能改已观察的参数。将真实复核写入该批 formal/semantic-review.json，再使用已验证冻结清单的 `--resume-from server_import_backtest_audit` 接续服务器阶段。生产财务发布门槛仍由服务器最终决定。语义审计进入 cycle-summary，不会把未复核候选计成已上线。
