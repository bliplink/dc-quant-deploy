# CUSUM ADA：主期通过不等于完整本地资格

2026-11-11 08:08北京时间只读核对。原CUSUM21204仍在跑完整100队列，不改其冻结代码/数据/原金融程序。22个完成checkpoint全部重新核对，完整本地通过0：19个OOS失败、1个PF不足、1个扣费forward不正、1个独立留出失败。

## 这次真正达到哪一步

新作用域`catalog_adausdt_channel_0d97bf7a8908`，`cs1_standardized_drift_short`、ADAUSDT/channel，源码SHA74c3780056e9e61ebc1bd6740e2f63906061fd8024982e1fb5b41d53f456696b、JAR58b1e3c8d92022723fb7b29d569aad1751d7916e2851851d5b4b825d57caada2、seed c6ba2db6277d96235de1dacabdf09cb37c6838c8609634c3dbe92d85686e1d95。原validator/真实2023全年35040根对照517信号/0差异，canonical_proof_reused=false。

原主期2024-12-15～2025-10-12实际44笔、PF1.35779、DD4.1071%、总Pnl709.301468；扣费validate308.375807、forward260.378103、OOS1。原DTO贡献下限0仍须单独strict裁决：实际0.367091≥0.20，主期严格通过。这里没有改原DTO/结果或重放主期。

随后同一源码/JAR、空锁定参数、0优化/0拟合调用进入原独立62日2025-10-13～12-13：**22笔、PF0.892338、DD6.3281%、扣费Pnl−385.93538055、passed=false**。这是已有足够观测的真实亏损拒绝，不是编译错误或只缺样本；不能上传、当候选READY/SUCCESS算上线或反复调参重跑该留出窗口。

## 原始证据及接续约束

根`strategy-cusum-drift-formal-20261111/candidates/catalog_adausdt_channel_0d97bf7a8908`：checkpoint110202113ccd65cc1103d9df8377bec370f16bb91d5339bd46b69cc2bf7bd3f0，primary8b2e8d5de8df09f0360a96dfa161f263707330cd623be99d6a23b006f18cbe21，strict审计e1482d021730b872267e65c6e98035bc7071883d93b265b948f943240aadbaa6，holdout fb773d638c86f31876df818c6e2c440371c43381bfcf712833a3da3e30d631f5。原completed_case已验证全部冻结source/artifact/seed和金融哈希一致。

摘要快照`recovery/snapshots/cusum-holdout-rejection-runs-first-financial-20261111.json`；完整不可变原报告保留，不截掉亏损或换窗口。继续原队列尚未观测的新作用域；本条0本地完整资格/0上传/0发布/0LLM，不因主期达到门槛而偷换计数。没有新证据支持修复策略语义，不从留出亏损反推参数改动。
