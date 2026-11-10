# Signed-runs复用即将完成的分布策略槽位

2026-11-11 07:50北京时间真实启动观察：控制器13568/create1794354508.805948，模块`recovery.run_runs_profile_slot`，状态`WAITING_FOR_PROFILE_SLOT_COMPLETION`。这是已启动的等待控制器，不是已经接续/回测通过。完整证据见`recovery/snapshots/runs-profile-slot-start-20261111.json`。

## 为什么改调度

原signed-runs24444绑定CUSUM21204完成100后才开始，只是限制同时金融回测槽位，不依赖CUSUM收益来决定策略源码。分布策略20660的200项更接近结束，因此可在它自然完成后复用其槽位，避免其空闲、signed-runs仍等待更晚结束的CUSUM。不增加第五个金融worker，不改变100作用域或任何策略/风险/金融政策。

## 接续前的硬检查

- 分布策略必须精确匹配PID20660/create1794330108.9962358/原模块、output及manifest cce5da0df561e347ab2062810e48326cbab16879d630a64cfaa68c43fb4c8af0，且进程真正自然退出；同PID/create仍活着，即使命令改变，也不算释放。
- 必须真实完成200：原manifest、FORMAL_COMPLETE、status、200个唯一作用域/方向/mode、每个原completed_case检查的源码/JAR/seed/金融产物和checkpoint哈希、资格计数全部一致。退出、缺marker、部分完成、FAILED均不足。
- 原signed-runs24444/create1794348475.3380008仍须精确匹配原command/output/manifest 8df12c9516fac173c4b4abfdf6b35020b171dad67a4930aaf23f6b26b90eb601；保持0/100、原父CUSUM仍活着、无任何计算孩子、源码目录、classes/frozen/candidates/results/STARTED/终态。
- 新树中原runtime的每份Python必须与原冻结proof字节相同，原Python成员不增不减；真实verify_context的源码、class、数据、运行时、9FIT/12locked、协议和完整100queue必须等于原proof，只有新增控制工具的哈希可增加；原旧工具绑定仍保留。

真实预检通过24份source/config、790份工程class、2074份工具/证据、30数据、2288运行class、68JAR以及原Java选择/options。新增16项控制测试，完整337项Python通过38.469秒/退出0；原日志SHA3098ef60f9b5ee0245c7bee7fb6abbf0ca38d78071d73adcf703fff5c4b50085。测试中的合成checkpoint不是金融通过证据。

## 所有权转移及执行

仅分布200完成并核对后，旧output独占claim、独立guardian READY、精确旧编排parent暂停，再次检查零调度/无计算孩子/原上下文和分布完成证据，才停止旧的**空闲编排parent**。不终止计算；转移前失败或控制器崩溃时guardian恢复原暂停parent，而不是重放已停止的金融工作。

旧目录保存ORCHESTRATION_HANDOFF，不写伪COMPLETE；新旧output同时OS锁独占，新的独立金融根重新绑定全proof，然后直接调用未修改的`original.run_finance`/原`run_case`，100个原作用域全部保留。strict贡献>=0.20、原主期、分离62日留出、scene/费用/风险/样本及服务器门槛不变，没有训练cache hook。

## 继续工作入口

- 冻结工具树：`E:/sourcecode/codex/_work/dc-quant-deploy-runs-profile-slot-20261111`，源commit6bada008a95db81f820b1bcfbdad47f9a77c6836。
- 控制根：`strategy-runs-clustering-profile-slot-control-20261111-v2`，PREPARE_COMPLETE SHA9b0b7c9f9c1f1fa58db513dd3be9f961ef798e8b073684eb5e022e47e7c7ccd9。
- 日志：`strategy-runs-clustering-profile-slot-launch-20261111-v2/{stdout,stderr}.log`。
- 原等待根：`strategy-runs-clustering-formal-20261111`；目标金融根：`strategy-runs-clustering-profile-slot-formal-20261111`。

07:50目标根仍不存在，旧24444仍活着且没有handoff，不能宣称已迁移。先看精确owner、控制小status、PROFILE_COMPLETION_AUDIT/retirement/handoff以及目标manifest/不可变case；不要按旧WAITING重复启动24444或13568，也不要看到锁文件就当活进程。初版control（不带v2）仅为旧source预检历史，后续guard更改已使其失效，必须保留而不能执行。

此控制器真实启动后，本树全部Python冻结；后续开发另开树。生产、订单、持仓和待用户单独批准的固定空参数发布器修复均未更改。0新增资格/发布，100真实合格目标仍未完成。
