# 递推Fisher正式执行链：已启动等待，尚无金融结果

2026-11-11 08:44北京时间真实观察。继[完整工程通过](ehlers-fisher-research-20261111.zh-CN.md)之后，原正式主期/严格校验/独立留出执行链已在NEW工具树实装并启动。**启动的是100作用域等待队列，不是100条合格策略，也未开始金融回放。**

## 直接复用原执行，不改变门槛

新`recovery.run_ehlers_fisher_batch`直接调用原`run_ohlcv_profile_proxy_batch.run_case`，没有训练cache hook。整个run_finance函数体与原signed-runs版逐字相同，仅输出日志标签不同，测试已核对；只有冻结源导出器/工程证明换为递推Fisher。原主期2024-12-15～2025-10-12、strict贡献>=0.20、分离62日2025-10-13～12-13、scene/费用/OOS/样本/风险门槛、空锁参/0优化保持。金融成功后仍须当前同行复核、服务器固定源正常365日与发布门槛，不由本队列直接发布。

原20份10品种行情/场景文件逐份SHA核对并复制到协议视图`strategy-ehlers-fisher-temporal-input-20261111`，字节未变；10份训练文件仍用原根。新READY SHA56ae485dd7d865fe8977c9d4244429f85d03255bbc21f6ebd384e627fc666eb9，原READY来源8d919223d4d8de9b80de01e01fb38a2b15418d3e7f33ff0725157eb7ba9bccaa。没有重新采集、改数据或根据新金融结果挑选作用域。

新增15控制测试，完整364 Python通过40.475秒/退出0，日志`ehlers-fisher-formal-tests-4ce9aba9ebc940f5ad175e141ec15877/unittest.log`，SHA3ca9e875ba8179e08d0675822f703bcbe083d27e61b5ca6e05788cc26df4f318。真实预检重新核对27源/配置、798class、1946工具/证据、30数据、2296运行class、68JAR、原9FIT/12locked及整个确定性100queue。预检不创建金融输出或调用金融执行器。

## 为什么绑定CUSUM，而非较早说明中的signed-runs

两者都是可复用现有槽位的方案，不依赖父队列收益决定Fisher规则。实际核查时CUSUM为49/100、signed-runs为30/100，CUSUM更接近完成，且没有其他活跃等待者绑定它；因此本次**明确绑定原CUSUM21204**。不绑定已退休24444，不假造旧根完成，也不同时增加第五个金融worker。

精确父identity：21204/create1794339627.8894458/module recovery.run_cusum_drift_batch，金融根strategy-cusum-drift-formal-20261111，manifest1878a3edac0508ba2811de3e5bdbc007dc709982d69b10d4e968226eaab00916。当前原活进程完整command已保存到`strategy-ehlers-fisher-parent-binding-20261111/identity.json`，SHAda355a0bb58135f11e7c49896a1dd716e242246277c501d7b79f6a3157492bf8。父后续退出时也不选新PID或换manifest。

必须父**自然退出**，真实FORMAL_COMPLETE/status/原100queue、每条completed_case的作用域/source/JAR/seed/金融/checkpoint、资格计数全部通过，才替换那一个串行槽位。新增守卫还拒绝“同PID/create仍活着但command改变”的假释放，完整marker也不能绕过。父FAILED、消失但无完整marker、部分状态或任一产物变化均停止新队列，不重放父金融。

父退出后再重新verify_context，须与等待前完整proof相同；原3GiB/8GiB守卫不降。不要在下游已绑定期间任意替换/重启21204或改其冻结代码，否则必须保留实际失败并另做可审计接续，不能偷偷改新队列的父标识来过关。

## 实际启动与接续入口

- 工具树`E:/sourcecode/codex/_work/dc-quant-deploy-ehlers-fisher-formal-20261111`，源4f544a69d7b61d14034bfaccd7130ba7e736accc；旧工程树/Native不改。
- 实际owner **4748/create1794357859.699664/module recovery.run_ehlers_fisher_batch**。
- 正式根`strategy-ehlers-fisher-formal-20261111`，manifest **8f0283225dc48385eb8ee86e23193a15210e7859f9ae4d07f1a361d107aa15d0**，schema frozen_ehlers_fisher_100_scopes_v1。
- 日志`strategy-ehlers-fisher-formal-launch-20261111/{stdout,stderr}.log`；只读启动快照`recovery/snapshots/ehlers-fisher-formal-start-20261111.json`保存精确命令/父绑定/证明计数。

08:44实际WAITING_FOR_BOUND_CUSUM_BATCH/0of100，只有conhost孩子，没有classes/candidates/frozen，没有FAILED，金融dispatch=false。**从真实启动后，本NEW正式树的全部顶层Python也冻结**。后续开发再开树；不从等待状态/锁文件/一次观察超时盲目重启4748或父21204。先核实精确PID/create/module/output，观察小status和不可变完成case；原失败/负结果不能当参数搜索重跑。

100作用域、两方向和旧raw变换近亲仍只算一个保守Fisher家族，不把版本数当经济独立策略。0金融新资格/0上传/0发布/0LLM，固定空参数发布器修复仍待用户单独批准；100真实生产合格目标未完成。
