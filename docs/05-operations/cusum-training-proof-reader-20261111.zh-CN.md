# CUSUM训练证明读取器：已验证拒绝边界，尚未接入运行队列

记录时间：2026-11-11 04:58，北京时间。

本轮没有新增可上线策略。该读取器是完整训练证明的只读验收工具，不生成交易收益、不执行主期或留出、不连接服务器，不代表训练缓存已经启用。100条真实生产合格策略目标仍未完成。

## 代码与真实验证

新隔离目录：`E:/sourcecode/codex/_work/dc-quant-deploy-cusum-training-admission-20261111`；分支 `codex/cusum-training-admission-20261111`，基于原完整矩阵工具提交 `0e04487`。没有覆盖正在运行的矩阵/CUSUM/时钟/OHLCV/完整目录Python代码。

- 新增 `recovery/cusum_training_proof_admission.py`，SHA256 `3527f9283831695a835e6d2bbb9486924c70a3777f71e40a09474ec74801c9e9`。
- 新增 `recovery/test_cusum_training_proof_admission.py`，SHA256 `c69bf53f9257617325f5eae1dff66bdd83c2ed97949dda5aba8c1cb082b4b5b6`。
- 新增14项控制测试随完整253项Python回归通过，37.140秒，实际退出0。测试结果是软件行为证据，不是253条策略。
- 原始测试日志在私有目录 `cusum-admission-tests-stdout-7f68410279db4cd1b55b7b3759321ef0/unittest.log`，原始SHA256 `0681ab939a94f245e9d64aba0acdf7234cc2f1ed287bddf79f212b8d8a0b2cbd`。
- 对真实运行的3948进程核对创建时间1794342593.785792及module后，实际调用读取器，正确拒绝尚无MATRIX_COMPLETE的矩阵，未打开在写的matrix.json。
- 真实重新核对939关键文件、2280类、68运行JAR、训练输入、Java选择及选项环境；没有用假fixture代替这些实际环境检查。
- 真实逐文件审计两个已完成ADA方向组，每组五份源/JAR/seed/validator、三份完整类、原全年35040根信号日志均匹配；多头467、空头517信号，各0差异。完整矩阵仍仅2/20组、10/100份证明，不能据此验收其余18组。

首次12项专测及当时完整251项已通过；补充两项后，首次尝试用PowerShell `ErrorActionPreference=Stop` 加 `2>&1 | Tee-Object` 收日志，unittest的stderr进度点被当作NativeCommandError，shell退出1，不能声称该次253项回归成功。失败目录 `cusum-admission-tests-final-bad8d74adabe47c3a4a239bc9f2678bf`原样保留。随后仅将测试Runner的stream显式设为stdout、仍用同一discover与断言，完整253项通过并保存上述原始日志；未改金融逻辑或重跑金融观察。

## 读取器保证与未完成部分

1. 在读取matrix.json前要求无FAILED、完整MATRIX_COMPLETE及COMPLETE状态20/100；不能把锁文件、意图或部分组当完成。
2. 固定原manifest `a074c787bacd4a61f605113303636f76c4ca42dcb4e5f6867ddd036ced908e02`、context `7ef5634ee42c5ee6d14c66bc4afe8a2b99b7494a490426dfa7856e75470a9864`，调用者还须提供真实完成后另行固定的matrix SHA。没有预造最终SHA。
3. 必须20份真实全年参考、100份编译/validator/完整覆盖，逐组不可变marker、canonical和全部scope记录及各自源码/JAR/完整场景seed/参数profile匹配。
4. 重算严格源码两身份替换及完整三类字节等价，原全年日志必须35040根/数量一致/0差异；零信号仍是零覆盖，不能伪装成有效信号。
5. 前后重查完整环境、类/JAR成员及字节、原工具/训练文件、Java执行文件选择和Java选项哈希，不打印选项值。
6. 后续消费者还须绑定自己的精确scope、源码与完整场景seed，不得拿另一品种、方向或场景参数复用。

所有返回仍明确 `runtime_reuse_enabled=false`、`financial_validation_started=false`、`production_write=false`。该代码**没有接入任何实际run_case或活动控制器**，当前完整矩阵未完成，因此尚不存在真实全矩阵成功读取，也没有端到端缓存金融执行证明。下一步等真实20/100完成并固定最终SHA，再做实际全量读取验收；之后才另行实现/验证安全交接与训练检查复用。不能把读取器单元测试当成已完成这些步骤。

原实际主期回测、严格贡献门槛至少0.20、独立62天留出及服务器365天资格/正常发布必须逐策略保留，不跳过。固定空参数发布格式修复仍待单独明确同意，未动发布器、生产、风控或旧失败结果。

## 当前实际金融队列

20:58:37 UTC快照：完整目录843/19,599，raw2/strict1；strict1仍是此前服务器拒绝的ADA/channel，不能重复导入。OHLCV89/200，0本地通过；时钟67/100。较早逐条核验的66份时钟checkpoint/金融/源合同哈希中61份OOS未通过、5份样本不足，0合格；不把这个66份快照扩充冒称67份已审计。

CUSUM原21204继续等待原23812真实100结束并核验，仍0/100、未dispatch；完整矩阵3948继续计算/资源等待，3GiB守卫不降低。所有主进程均已按PID+创建时间+module实际核对，未重启旧27328/12040、未杀计算worker、未重放部分金融目录。

机器本地技能已补充 `dc/references/quant-training-proof-admission.md`，只记录接续和拒绝边界；skill-creator验证先遇Windows默认GBK解码失败，改用Python `-X utf8`后显示Skill is valid，不改验证器或技能原编码。
