# MD 分区级全市场追平审计——阶段结果（2026-10-10）

## 真实代码进展

[MDSvr `7f9cd830`](https://github.com/bliplink/com.app.dc.mdsvr/commit/7f9cd830737e464669210a162ddc0a16b936d89a) 在 `saas-crypto` 中新增：

- `MdPartitionMarketCoverage.inspect`：对指定分区、epoch 的**每个列入清单的市场**，核对本地完整行情快照和连续增量观察是否覆盖给定源序号，且在规定时效内；任何市场缺失、断档、epoch 不同、序号不同、越界分区、清单为空或未申报本地市场，均失败关闭。
- `MdDepthReplayWitness.marketKeys`：可读的本地市场键集合；不承诺跨市场原子快照，不能单独用来做晋升证明。
- `DepthBookFacade.inspectLocalPartitionCoverage`：在真实行情采集链路上调用上述只读检查，供未来权威清单接口调用；当前**尚无 OrderSvr 权威分区活跃市场清单输入**。
- 10 项分区覆盖测试 + 真实 `DepthBookFacade` 集成用例；全量 **79 项 Maven 测试通过、0 失败、0 错误**。

**必须避免误解：**此时传给比较器的 `expectedSourceVersions` 还是**外部提供的参考清单**，未验证来源、权威市场枚举完整性、持久化 WAL/Projection 或跨节点原子性。`Result.canPromote()` 永远返回 **false**，即使 `hasMatchingProvidedInventory()` 为 true，也只是“和这份输入清单匹配”，**不能用于实际 ZK 主节点晋升**。生产 MD A/B/C 未更新镜像、未重启、未注入新的主节点故障。

## 下一步实现必备的真正晋升证明

1. **OrderSvr 权威不可变分区 manifest**：必须由当前已 fenced 的写入主节点为整个分区给出确定性市场全集、每市场末端事件序号/epoch、完整快照版本、来源身份和提交水位；不能由候选副本自行编造清单；空清单、未证明全集、遗漏市场必须拒绝。
2. **持久化完整性**：manifest 及候选市场快照/事件连续性需可核对签名/摘要和 durable watermark；当前本地内存 `MdDepthReplayWitness` 不构成持久化证明。还要与 Order/Trade/Projection 权威一致性对账。
3. **跨节点协议**：确认两个合法、已追平且存活的副本，控制器具有可写 ZooKeeper 会话/唯一租约；晋升前再次校验旧主死亡和同步水位，通过 ZK versioned CAS 修改 epoch/primary，旧 epoch 彻底被读/写/订阅栅栏拒绝。旧主恢复时作为 Learner 重追平。
4. **隔离三节点故障测试**：十租户连续撮合与报价下对 MD Primary SIGKILL，验证完整行情集合、两个副本水位、epoch 切换、无双主、无旧盘口、Robot 自动恢复、权威成交与资金一致性，完成旧主归队和角色反转后才允许在 Mac Demo 再次受控注入。

当前十租户保持正常运行，尚未授权 25/50/200 租户扩容，也不得因为单项源码 CI 成功就宣称 MD 主节点故障切换验收通过。
