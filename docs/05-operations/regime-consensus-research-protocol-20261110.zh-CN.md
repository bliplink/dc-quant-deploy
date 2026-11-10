# 跨历史阶段共识策略：财务检查前冻结协议

## 动机及明确不变项

2026-11-10只读审计发现，生产库10个目标品种15分钟K线最早均为2024-08-12，没有更早训练行情。之前的冻结训练只能覆盖约四个月，不能代表跨阶段稳定性。新的假设是分别训练2022、2023、2024年度模型，推断时固定取三个年度预测中位数，不选择赚钱最多的年份，不平均放大单个年份的极端预测。

每年度保留动量、相对价值、波动、时段/价格成交量四组，岭回归与浅层提升各一类；多空分开训练。共48个数值子模型，但只有8个策略类、16个候选方向，不得把年份或子模型数算成独立实盘策略。

训练过程固定原有alpha=200、24棵树、深度2、最小叶100、学习率0.05、种子20261110。48个子模型使用验证之前的数据，完整潜在96根标签观察窗必须早于2024-12-15；年度标签还须在对应年内实际结束。特征与标签窗口有缺失K线就排除，不补造行情。入场仍为预测扣费净空间>8bps，且比反方向中位数净空间高8bps；ATR风险和所有本地、服务器资格门槛保持不变。训练标签的代理局限沿用执行路径文档，重叠标签不声称独立显著性。

原冻结财务READY、验证期、留出期、失败观察全部保留不动。这个年度共识设计须在读取本批验证财务结果前确定，不能看到结果后改年度组合、权重、阈值再跑相同前瞻。

## 数据来源与对齐证据

使用[币安官方公开数据说明](https://github.com/binance/binance-public-data)中的USD-M合约月度15分钟K线归档。每份下载先核对官方SHA-256 CHECKSUM，ZIP仅在内存读取单一预期CSV，不提取任意文件路径。无API密钥、不改生产数据库、不触发服务器回填或DeepSeek。

第一次BTC重叠比较被拦截：1,920根OHLC价格全部相同，只有成交量差异，最大0.009。核对仓库DDL确认`dc.kline`及`kline_view`成交量是Decimal(76,2)。明确复现原有十进制两位向零截断后，10个品种各1,920根、合计19,200根OHLCV逐项一致。没有放宽比较容差或更改价格。原失败数据目录保留，新目录使用明确的规范化版本字段，不能混用检查点。

原始检查：`strategy-public-training-overlap-20261110`；确认对齐检查：`strategy-public-training-overlap-scale2-20261110`，`DOWNLOAD_COMPLETE.json`及`overlap-audit.json`均已完成并通过。

更早训练归档范围2022-01～2024-07，共310份；北京时间14:40:28以进程24224开始，目录`E:\sourcecode\codex\_work\strategy-public-training-history-20261110`。下载是本地只读市场数据操作，完成数量不代表策略数量。

## 本地工具与接续顺序

1. 检查`strategy-public-training-history-20261110/download-status.json`及`DOWNLOAD_COMPLETE.json`。如有网络失败，原命令可恢复；已完成TSV须逐个核对冻结哈希，失败不能创建完成标志。
2. 用`recovery.assemble_training_history`合并更早归档、8月1～11日桥接及原冻结输入中8月12～12月14日训练前缀。参数分别是`--archives-dir`、`--overlap-dir`、`--existing-input-dir`、`--output-dir`；新输出建议`strategy-regime-training-input-20261110`。产物为新的`purpose=training_only` READY，绝不覆盖原研究READY。
3. `recovery.train_regime_consensus_models --input-dir <training-only input> --output-dir <new model output>`，建议模型目录`strategy-regime-model-training-20261110`。要求三年度模型齐全，否则不静默退化；模型包冻结后不得覆盖。
4. 将冻结权重/树嵌入独立研究工作树`indsvr-local-regime-consensus-strategies-20261110`，增加Java/Python数值、时间、窗口、未来访问和目录注册测试。该工作树已从执行模型最终版本7ed0854创建，但此协议提交时还没有完成模型生成，不要误认为已可实盘。
5. 按相同完整流程预筛、正式/留出、固定源码服务器导入、365天回测和真实资格核验。仍只上传双重本地合格源码，禁止服务端生成/修复。

当前新工具连同既有流程共42项Python测试通过；执行模型Java测试42项通过。这些仅是程序正确性证据，不是盈利证据。当前生产合格4、缺96，持续目标未完成。
