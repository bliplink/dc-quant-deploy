# ADA趋势区间边缘反转：本地严格通过，服务器复验拒绝

2026-11-11 06:54北京时间终态。本次实际完成一次固定源码导入、服务器编译、完整365日回测及原发布器判断；**新增实盘0**。不重试此已消费的失败源，不调档/换窗口凑数。

## 本地原证据只读核验

候选 `catalog_adausdt_trend_26182569b6b5`，原队列 `fr1_median_true_range_edge_fade_long_s20_t40` / `FitOnlyRiskMedianTrueRangeEdgeFadeHypothesis`。完整目录第1078项得到本地严格通过，controller严格数由1增至2；旧1是已服务器拒绝的ADA/channel，不能误当两个新实盘。

调用原 `verified_observation` 与原9例FIT `require_proof`：source/JAR/合同/完整seed/四档candidateParameters/完成marker与金融输出SHA均匹配。旧DTO的minForwardContribution=0未当发布资格，上传前仍按原至少0.20裁决。

| 项目 | 原主期 | 完全分离留出 |
| --- | --- | --- |
| 日期 | 2024-12-15～2025-10-12 | 2025-10-13～12-13 |
| 交易数 / PF | 23 / 1.284158 | 10 / 2.167285 |
| 最大回撤 | 0.039425 | 0.026670 |
| 扣费验证 / 前向 | 96.223928 / 94.447571 | 扣费总收益310.85474162 |
| 参数 | 四档逐折FIT，代表riskProfile1 | 锁参1，fit/optimizer均0 |

原主期totalPnL303.775807、OOS1、严格贡献0.310912。留出10笔只是有限样本，不保证未来盈利。

- 原固定plan SHA `59944b8d1fcb4f504cb129e29c49956da064e5c6270bce1409b47b6db2a1c347`。
- 源SHA **2f9c1905f65aa059aac37fca627269176c869a3a4a4eea303807a02040643b34**；本地JAR `d5133526f2e6c39647320a16fbead05769c1980eccd5528238384491a161ae20`。
- results `5c30cfc4fd59a088650ea809195062a3658c1b183a83c7a763faf8afc81a393a`，local-pre-admission `23d5890c0502aa0b39ae2abd0ec0f3837cbec34fa85897894f68af7b9fb7e2cc`。
- 原admission `strategy-fit-risk-full-catalog-20261110/admissions/catalog_adausdt_trend_26182569b6b5`；单条原results与frozen逐字节复制至 `strategy-risk-median-ada-promotion-view-20261111`，未改原活动队列。

## 当前同行审查与上传前检查

22:48:34UTC新库存与22:48:41UTC精确源码备份均4 ACTIVE。唯一同格同行 `wb15_trend_t019_u70080@v2` 源SHA `4b0f51550a6304d71dfbf0ce1020b7f527e34dccfbcfcef2dce29bd664408e2c` 是20根突破后的回踩，并要求8根方向/区间强趋势；新源warmup180、前120根均线漂移<=1.2%、ATR14<=64根中位TR的1.15倍，前49根箱底8%触及后当前收盘突破前高，是真实规则差异，不是改名或风险档变体。仅批准1个quiet-box edge-fade实例，不声称统计正交。

新源不是此前失败ADA/channel的96均线-minus1.8ATR两步包络重入重试。完整私有同行源码留在 `strategy-risk-median-ada-peer-review-20261111`，不提交公开repo。

真实host及固定SSH host-key匹配prod-mooncake-standby，UTC日期2026-11-10，最近完整日2026-11-09。prepare-only先通过semantic review、strict和原source validator；准备的38,254字节上传源SHA与原冻结源完全一致，未做标识符变换。保留原四档FIT政策，没有用留出选新档。

## 实际服务器终态

本地轮询器 **24956/create1794351084.6402376** 正常结束；不要重启或重新导入此源。

- v1，generation `gen_1569967808865951744`；candidate `cand_1569967823529238528`；backtest `bt_1569967824271630336`。
- 请求/实际2025-11-10～2026-11-09完整365日，120/30/14、FEE_ADJUSTED_PROFIT_FIRST；新窗口原政策代表riskProfile3，本地1，属于新窗口原FIT规则，不强制改成1。
- **22笔，PF0.935043，最大回撤0.021683，totalPnL−69.132715，扣费验证−266.379344，扣费前向−783.469493，OOS0**。
- 场景726记录/3320匹配bar/22笔，qualification=false。原publisher **SKIP / scene fee-adjusted pnl <= 0**。
- 编译与回测任务SUCCESS、candidate READY，但精确版本registry空、published=false；SUCCESS不是实盘ACTIVE。
- external / EXTERNAL_SOURCE / EXTERNAL_IMPORT / external_java，精确版本LLM调用 **0**、无fallback。上传与存储都38,254字节但SHA不同：仅允许的package-header空行及末端ASCII空白规范化，tokens unchanged。存储SHA `992ae1e31b343d0f500961b7110fa2735bffd44784602d24870401d2186b84a9`。
- 服务器JAR及candidate.checksum一致：`67f8d3aaef256785f49c8e54838d847b47dbec7a0e6df7a18b5c354ba5b4ddd4`；compiled_source_verified=true。

证据 `strategy-95-server-fit-risk-median-ada-20261111/catalog_adausdt_trend_26182569b6b5`，日志 `strategy-95-server-fit-risk-median-ada-launch-20261111`；公开摘要及全部请求/终态/源码审计文件SHA见 `recovery/snapshots/fit-risk-median-ada-server-rejection-20261111.json`。首次终态只读默认GBK解码失败，显式UTF8重读即成功；没有再次提交或金融重放。

22:54:09UTC / 06:54:09北京时间生产新库存仍 **4 ACTIVE/当前运行资格，另2过贡献单项**；本轮0新增发布，100目标未完成。没有服务镜像/配置/风控/持仓改动、重启或直接registry写入。继续原未消费OHLCV队列；该源服务器失败已消费，不据此调参、回捞旧版或再次生成。
