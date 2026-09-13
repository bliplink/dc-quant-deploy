# TradeSvr 集群底座边界与后续实施

## 当前落地范围

- TradeSvr 路由维度固定为 `location`，一个租户的余额、持仓、保证金、资金费、强平与 ADL 状态不拆分。
- OrderSvr、LiqSvr 和 Web 发往 TradeSvr 的请求均携带 `location` placement key。
- A/B 使用相同不可变镜像，通过独立 `serverKey`、端口、存储目录和日志目录区分实例。
- A 节点运行现有业务；B 节点默认 `trade.node.businessEnabled=false`，只作为禁止写业务的冷备骨架。
- `TRADE_CLUSTER_ENABLED=false` 为默认值，因此本阶段合入和发布不会改变现有单节点生产路由。

## 明确未完成的能力

当前版本不具备 TradeSvr 安全故障接管能力，不得在生产开启 `TRADE_CLUSTER_ENABLED`。在完成以下能力前，不能把 B 节点标记为可承载流量：

1. 按 location 记录可校验、单调序号的余额/持仓/订单状态 journal。
2. A 到 B 的同步复制、ACK 策略、积压上限和降级策略。
3. 一致性快照、快照后的增量回放、epoch/fence token 与启动恢复门禁。
4. ProjectionSvr 消费成交、余额、持仓与资金流水事件，提供可重建的查询投影。
5. 故障注入验收：进程退出、网络隔离、复制中断、角色切换和双主防护。

## 后续启用流程

1. 部署包含复制与恢复能力的同版本 TradeSvr 镜像，但保持集群开关关闭。
2. 在隔离 Compose 项目启动 A/B，执行历史状态基线、增量追平和校验。
3. 写入 location placement 清单，确认每个租户只有一个 Primary，Replica 已追平且 fence 生效。
4. 完成下单成交、资金变化、强平、ADL、重启恢复和角色反转验收。
5. 生产按租户灰度启用；任何校验不通过立即停止迁移，原单节点继续服务。

这套边界的目标是先统一调用契约和部署身份，不以“能启动两个容器”冒充可用的交易集群。
