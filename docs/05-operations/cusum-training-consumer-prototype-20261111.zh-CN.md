# CUSUM训练证明消费者原型：金融执行段保持原样，活动队列尚未切换

记录时间：2026-11-11 05:12，北京时间。目标仍是补齐100条真实生产合格策略；本轮0新增上传/发布，不能把软件测试、训练证明或消费者原型当成可上线策略。

## 实际代码和验证

新隔离目录 `E:/sourcecode/codex/_work/dc-quant-deploy-cusum-training-consumer-20261111`，分支 `codex/cusum-training-consumer-20261111`，基于读取器提交 `a081e7e`。原矩阵3948、CUSUM等待21204、时钟23812、OHLCV20660和完整目录24052及各自冻结Python没有修改。

- 新 `recovery/cusum_training_consumer.py`：SHA256 `d6316e7f56c3d92e6129254a0c35bad5541bb98214870a621ebfee2513c29311`。
- 新 `recovery/test_cusum_training_consumer.py`：SHA256 `fb2ac34f83fb06c08b5e515956eac4595b867c4caad2e6db45901d53c8e2cd03`。
- 仅在新树给 `run_ohlcv_profile_proxy_batch.run_case` 增加可选的 `training_proof_resolver` 与源合同回执。未传入时保持原编译、原validator、原全年对照和金融路径；任何活动控制器目前都没有传入这个新参数。
- 新树该模块LF字节SHA256 `5fd95bba9d90288e015f2924999b5017d6708bb1e07376c7f4c48a2ad5a6c1db`。金融部分从 `files = ready['files'][row['symbol']]` 到run_case结束，与真实正在运行的旧文件进行LF规范化后逐字节相等：3934字节、SHA256 `7feaa47b44aed5f1db03e772671098282279ac602832b96264176ac413171609`；测试亦固定此原始摘要。
- 新增14项消费者/执行控制测试最终通过；完整267项Python回归先在CRLF工作副本通过41.377秒/退出0，再仅将新树该文件规范为LF后完整267项通过27.874秒/退出0。没有修改任何Java金融helper、原引擎或财务门槛。

最终LF回归原始日志私有路径 `cusum-consumer-tests-lf-11bbee5480cf4119b75880769128b2b6/unittest.log`，SHA256 `323074256b331b0fc3a8f1d323dbef67aeb782d86c1c1f9d79b9e3a76c4e8a5b`。之前CRLF回归日志在 `cusum-consumer-tests-48dbc9f97a0a4dd28269ab653c1a658b/unittest.log`，SHA256 `e04a7ade91f856bada6c538bcbd3d3303200fe41dab1cf56af454db991891ee4`，均保留。

首次14项专测中13项通过，1项报错：人工strict-pass夹具缺少原执行器正常读取的 `reason` 字段。失败源码完整保留在 `strategy-cusum-training-consumer-engineering-failure-20261111`，原测试SHA256 `a35a6e26a5151dc969599c5381f728788617e935c04d3b02c99f1e6c6142773a`；只补齐测试夹具，未改原金融逻辑。不能把该首次运行称为通过，也没有重跑任何真实金融失败窗口。

## 证明消费者的边界

构造 `VerifiedCusumTrainingResolver` 必须先调用上一版完整读取器，要求真实完整20组/100源码及外部固定最终matrix SHA、原manifest/context、完整环境和全部不可变证据。当前真实矩阵还未完成，构造器已实际验证会拒绝它，未产生可用resolver，没有读取在写的大matrix.json。

后续每次消费仍重核终态和环境、自己的scope/源码/完整场景seed、对应五场景组与三类字节证明、自己的JAR及真实canonical全年日志，再生成带matrix/group/scope/源/seed/JAR/log摘要的回执。run_case在金融启动前再次核对回执和自身字节，空证明/错误证明不能退回其他来源继续。

14项新测试覆盖：构造阶段拒绝、终态/环境变化、错品种/方向/场景、源/seed/回执变化、原金融尾段字节、主期不合格、raw-pass但strict拒绝不跑留出、strict通过仍跑原62天留出、旧无resolver路径仍编译/validator/全年对照、已完成或部分目录不重放。**这些执行流测试使用人工金融输出替身，不是真实市场的缓存金融回放，更不是盈利证明。**

## 真实源码绑定，不冒充完整缓存准入

在独立私有目录 `strategy-cusum-training-consumer-source-bindings-20261111-v1`，用实际原导出器重新导出已完成三组、共15份当前源码和完整seed，对照原不可变证据逐份验证；环境939关键文件/2280类/68运行JAR前后重核。

- ADAUSDT多向：原全年35040根、467信号、0差异，五场景。
- ADAUSDT空向：原全年35040根、517信号、0差异，五场景。
- BNBUSDT多向：原全年35040根、444信号、0差异，五场景。

真实绑定审计生成于21:09:55 UTC，原始 `audit.json` SHA256 `77851485b5eb936e4cbd0dd57418ebf403f123dd181978f5fa65a25eaef5b6fe`。该审计发生在换行规范前，明确保留当时run_case模块原CRLF摘要 `b75adc8c59edfbb1393e5b65292aa8a69cfee346c4774029391779216cde927c`，不能把它改写成后来的LF摘要；原导出器、消费者、源码/seed/JAR证明内容未改变。

完整矩阵仍仅3/20组、15/100份证明，后续仍计算或等3GiB资源守卫。部分组审计及15份重新导出不是完整矩阵准入，也没有通过此新hook执行真实金融回放。

## 下一步与不能做的事

1. 等原3948真实完成全部20/100并固定实际最终SHA，再真实验收完整矩阵和消费者全部100个scope；不能为便于测试伪造完成标记。
2. 新路径还须验证真实人工数据的原金融helper执行等价及端到端合同；目前只有未改金融尾段、人工替身控制流和部分真实源绑定，不能宣称此项已完成。
3. 实际接入必须另建冻结manifest及安全所有权交接：原21204若仍0金融，只能核验无dispatch/无计算孩子后退休；若已开始，则等原计算自然结束并验证checkpoint，不能杀孩子、重放窗口或并行争抢同目录/同槽位。
4. 严格本地通过且独立留出通过的新源仍优先走机制去重和126服务器编译/最近365天/正常发布；不调用DeepSeek，不改原主期/至少20%贡献/样本/费用/OOS/留出门槛。

05:11实查：完整目录873/19,599，raw2/strict1，strict1仍是旧ADA服务器拒绝源，无新增；OHLCV97/200，0合格。时钟70份原completed_case全量校验，64 OOS/6样本不足、0合格；CUSUM21204继续0/100等待23812真实完成。所有五个原主进程按PID+创建时间+module再次验证存活，未重启旧27328/12040，资源守卫未降低。

dc技能参考已用skill-creator补充新原型入口与未完成边界，UTF8验证显示Skill is valid。固定空参数发布格式修复仍等待单独明确同意，发布器和生产没有变更。100策略目标保持进行中。
