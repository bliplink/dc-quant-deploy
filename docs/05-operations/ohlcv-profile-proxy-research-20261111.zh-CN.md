# OHLCV价格分箱代理：金融前新假设

2026-11-11开始，只用已有OHLCV，不增加外部因子/采集，不改服务架构，不使用DeepSeek。现有4332和24052队列/源码/规则/数据保持冻结。新代码在两个独立worktree：`indsvr-local-ohlcv-auction-profile-20261110`、`dc-quant-deploy-ohlcv-auction-profile-20261110`；目录日期为创建时间，不代表已完成或已上线。

新cohort为`ohlcv_profile_proxy_v1`，完整规则在`recovery/strategy_research_ohlcv_profile_proxy_protocol_20261111.json`，先声明再进行金融观察。128根已完成历史bar按typical-price分入32箱，将每根整笔volume作为代理质量，不冒充真实逐价成交量、订单流或订单簿。当前bar不进入profile，跨边界采用精确十进制交叉乘法，不放宽浮点容差。

两种事件为70%连续价值区重入到POC、双高质量峰之间低质量谷跨越到目标峰。原目录确有AuctionValueRejection/MultiAuctionBalanceEscape等命名，但实际是上一完整日VWAP/波动带或三个时段区间相交/突破；本分箱非其改名。依然保守把本次两个事件×多空4方向统一归为一个`ohlcv_distribution_auction`机制组，不按箱数/方向/模式/风险版本凑独立策略数。若将来合格，还必须与当前同单元实盘源码具体比较，不预先批准。

固定160根热身、最多200根可见历史、ATR14止损1.5倍、profile目标和既有ATR20显式EMS退出；无参数网格。先通过独立手工/原始报价数学oracle、边界/因果性及原源码校验，再做2023全年实际生成源逐字段对照。金融仍须原主期2024-12-15～2025-10-12、完全分离62天留出2025-10-13～12-13、既有20%或更高前向贡献和全部原门槛；最后服务器最近完整365日/场景/基线发布器。

当前仅开始工程研究，未执行本假设任何金融回测、上传或发布，不能把4个原型或将来的200个作用域当作4/200条独立合格策略。主期/留出失败不调参重试，不保证能达到盈利门槛或100条目标。

## 01:02工程终态及真实排队（优先于上面的开始记录）

工程V1目录`strategy-ohlcv-profile-engineering-20261111-v1`保留FAILED、源码哈希、编译类及日志：11项数学/行为测试过，但原源码校验器要求onBars信号赋值前显式保护多空stop/take方向。模板已有等价计算保护；只增加冗余明确guard，不改任何价格、阈值、参数或validator，未读金融结果。诊断临时调用曾传不匹配strategyName并多报名字错误，不是一次服务器尝试。

V2完整通过12项测试，包含64组独立区间归属/质量/价值区oracle、精确报价边界及最大端点、POC/相邻质量平局、70%含边界、零量/非法OHLC、四个非零合成setup、原风险与全部退出字段、160热身、200根淘汰、当前bar不进入profile、canonical all登记和未改源码校验。

4份实际生成源均通过原validator、独立编译及BTC2023全年35040根逐字段信号对照；信号276/292/344/277，全部0差异，4方向仍同一机制组。工程manifest SHA `d0352da4d6fbe80b50bfd1872f1bd30b4cc039fe144b1a4809fc77b8e4de2a6f`，目录`strategy-ohlcv-profile-engineering-20261111-v2`。源/JAR及全部编译类哈希在其status和完成marker，不把工程信号数当交易/资格数。

完整旧研究回归+新测试123项Java通过：`strategy-ohlcv-profile-regression-20261111-v2`，manifest `b5cb980a82257d3631134d980165fadfff9ce3fb6047e0a96ad0b20d6e4f33a4`。首回归编译缺Wick parity辅助类的失败日志保留；仅补齐旧辅助类编译清单后在新目录重做，无金融重放。

Python全量178项通过。首次工具测试暴露Windows临时handoff意图文件在原子替换期间短暂PermissionError；只在新工具树添加最多8次、仅权限/共享锁错误的有界元数据读取重试，不重试金融任务或吞掉损坏JSON。旧24052所在工具树完全没改。新增回归覆盖持续权限失败、损坏JSON不可重试；测试fixture不再依赖本机路径或重复加载同一TestCase。

Native本地`cdbdf8d`/`852b9f3`，研究远端分支`codex/local-ohlcv-auction-profile-20261110`已推`f4f5ef0a893cba18a093d15fcf95880cb73e8d1f`，tree `7c167fbae5c9623183cf334ba01b8b52ed9cd8c0`。5个blob与本地逐项核对，Core只新增独立cohort与all登记4行。已核对镜像工作流只在latest触发，本研究分支不部署生产，无POM/运行时/共享包变更。

## 固定金融队列已冻结，当前等待，不等于已回测

协议SHA `8750dc48f7120d75ec2d2462a2b69f83de65e902713f0e445bb9c8342b0f0b7a`。从原输入只复制同字节行情/场景到`strategy-ohlcv-profile-temporal-input-20261111`，READY SHA `839784d0712fffd4169d2f8a6713a1cbce7e4f6854f81fac441e40fc9263bfb2`，原数据不改。

新Git工作树曾把冻结Java helper检出为CRLF，已仅恢复为原始LF并逐文件确认逻辑相同；真实9例oracle源码哈希重新吻合 `5b29252b6355097ae408dddef3ca0cc02f89d3b3c39339ce03253db7ee551399`。新增精确`.gitattributes`规则固定recovery/java的LF，Git确认只改属性、没有helper逻辑差异；Native新模板亦固定LF。不得改oracle SHA去接受不同字节。

`run_ohlcv_profile_proxy_batch`在01:01:48以20660启动（create_time=1794330108.9962358），输出`strategy-ohlcv-profile-formal-20261111`，日志`strategy-ohlcv-profile-formal-launch-20261111`。金融manifest SHA `cce5da0df561e347ab2062810e48326cbab16879d630a64cfaa68c43fb4c8af0`，冻结10品种×5场景×4方向/模式共200作用域，无参数网格、只有1机制组；当前状态`WAITING_FOR_BOUND_BALANCED_BATCH`、0/200、没有本假设金融回放/上传/发布。

绑定4332的创建时间、完整module/output及400项manifest；必须该原平衡批次真正BATCH_COMPLETE400且无FAILED，才自动开始，单纯PID消失/换号不行。这是让出已有计算资源，不是依赖其盈利结果来调新规则。01:02原4332仍316/400、1本地通过（LINK服务器失败）；原24052继续完整目录，不重启旧12040。

接续会先查同一20660实际存活及小状态，不按等待状态重复启动。新正式链路逐作用域原validator/训练期信号一致性→未改FixedSourcePrimaryReplayCli实际v4→独立strict_primary_admission至少0.20（或更高）→主期全部过才执行分离62天锁空参/0优化留出。原DTO默认0不再让贡献失败者进入新留出。保留原始engine输出、strict审计、源/seed/JAR/金融哈希和失败；半完成目录拒绝重跑。

工具无SSH/模型/导入/发布路径。将来本地严格合格还需同单元真实源码机制复核、固定源服务器最近完整365日与正常场景/基线/发布器，不能直接写registry或重试已消费失败。最近服务器库存证据仍23:33快照4条运行资格、另2条过贡献；本轮未新增服务器发布，100条目标继续。
