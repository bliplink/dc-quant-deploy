# OrderSvr 四分区挂单入场 TPS 阶段性基线（2026-09-28）

## 测试边界

- 本报告只测 `placeOrder` 的非成交限价挂单入场，不把它称为完整撮合或全系统交易 TPS。
- 两个 OrderSvr 节点各承载两个 primary 分区：P044、P222 在 A，P135、P059 在 B。每分区独立测试租户与用户，BTCUSDT，每轮 1,000 单。
- HTTP 成功表示请求已被入场路径接受，不表示异步处理和复制已经完成。测试另以认证的 `queryOpenOrder` 确认全部新单在运行态可见；这仍不是逐笔 WAL 提交时间戳。
- `dc_orders` 是异步 SQL 查询投影。它的追平时间单独记录，不能并入 Order/Trade 核心同步 TPS。
- 每轮使用正常 `cancelAllOrder` 清理，随后验证投影中没有遗留活动测试单。未重启 Order/Trade/GW；本次结束时 256/256 分区 READY、A/B 各 128 primary、两侧快照集合一致，相关容器无新重启或 OOM。

## 已测结果

| 每分区目标 TPS | 每分区并发 | 四分区实际 HTTP TPS | 接受/请求 | 运行态新单追平 | SQL 投影追平 | 各分区 HTTP p95 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 75 | 32 | 约 300 | 4,000/4,000 | 约 2 秒 | 17–27 秒 | 166–201 ms |
| 100 | 32 | 约 398 | 4,000/4,000 | 约 2 秒 | 7–32 秒 | 471–586 ms |
| 125 | 32 | 约 376 | 4,000/4,000 | 约 6 秒 | 17–42 秒 | 667–702 ms |

另一次每分区目标 75 TPS、并发 16 的试验只有约 270 HTTP TPS；并发提高到 32 后达到约 300 TPS，说明此前至少部分受发压端在途请求数限制。目标 500 TPS 的试验实际只有约 376 HTTP TPS，不能将“500”写成系统实测值，也不能据此单独断定瓶颈一定在 OrderSvr。

当前**最高已验证的短时四分区挂单入场速率约 398 HTTP TPS**，请求全部成功，运行态在请求阶段结束后约 2 秒可见。它不是持续容量上限；单轮负载约 10 秒，而且尚未给出逐笔持久提交时间或完整成交链路的持续速率。一次独立的 100 组完整下单、成交、账务和平仓小样本通过，只证明功能闭环，不作为容量数字。

## 回头继续压测时

1. 先解除 TradeSvr/GW 内存余量不足的干扰：本轮末两个 TradeSvr 约 810–813 MiB/896 MiB，GW 约 452 MiB/512 MiB；虽无 OOM，TradeSvr 已出现 cgroup `memory.events max` 计数。核实堆、页缓存和回收压力后再做长稳负载。
2. 给负载发生器补实际发送时间和在途数观测，避免将并发槽位限制误判为服务端 TPS 上限。
3. 以更长时窗逐级测四分区和更多分区，记录 HTTP 接受、运行态可见、Order/Trade committed watermark、投影追平、p95/p99、队列深度及资源水位；用相同判据区分峰值与可持续值。
4. 单独测完整成交链路的持续成交/记账 TPS，不以 `taker-match` HTTP 返回速率代替最终成交 TPS。

本轮原始证据保存在本机部署目录 `.tmp-e2e-artifacts/stress-rt75c32*`、`stress-rt100c32*`、`stress-rt125c32*` 和 `stress-fullprobe0928`。脚本 `tests/run-core-trading-stress-host.sh` 的 `LOAD_VERIFY_RUNTIME_DRAIN=true` 会生成 `runtime-drain.tsv`，SQL 投影结果另记于 `admission-drain.tsv`。
