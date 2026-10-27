# T199 / T199b｜Common 认证 WAL 的实时业务副本 Apply

日期：2026-10-27，Mac mini Demo，saas-crypto，本地离线 ARM64 构建；GitHub Actions 未使用。
结论：实时业务副本追平链路在 T199 真实新订单探针通过；T199b 增加正常在途 WAL/custody 竞态保护，统一部署、冷重启及四节点运行通过。完整 Robot / 成交 / HA 故障切换仍 NO-GO。

## Common 公共层实际新增
- 每个业务节点只有一个后台工作线程，轮询本节点真实 Replica 分区（不是每分区一个线程）。
- 只有已物理持久化的 Common WAL 与原 A/B RSA 双签的 Custody HEAD 水位、全量字节及 SHA256 完全一致，且当前 ZK Epoch/租约有效，才通过业务提供的 VerifiedLiveBusinessReplay 对新连续状态变更做 Apply。
- 每分区保存已 Apply 水位，拒绝回退/跳序和未验证 WAL；回调失败毒化副本并拒绝继续声明 READY，不制造新客户端 ACK。
- T199b 修正正常时序竞态：下一条 WAL 已 fsync、下一份 Custody 尚未安装时不错误毒化节点。业务 Apply 开始后如失败则严格 fail-closed。
- 集群认证机制统一在 Common；Order/Trade 只负责自身业务状态解析。未引入新 HTTP 复制通道。

## 真实 E2E 证据
- 临时独立 Robot ID：R0F6CC / t199-signed-live；一个 Bid、一个 Ask，60 秒刷新，受控运行至多 20 秒，finally 中关闭，最终 enabled=0；原 e2e-depth10 继续关闭，未清空原有资金和 WAL。
- 新订单前：Order A/B 各 662 条（660 历史 Newing + 前轮 2 Maker）。
- **无重启副本的实时追平**：2 条新单后，Order A/B 各 664；两物理节点均报告同周期 addRequests=4、makerAdds=2；Order A/B 原始 WAL 同时增加 7,530 字节。
- Trade A/B 的 P246 WAL 也新增并保持一致。
- tests/T199ReadOnlyLiveWalQuorumProof.java 复核原独立 RSA 公钥和 Common 只读认证证书：Order P089 676 条已提交 WAL 帧、Trade P246 7 条，真实 A/B 全量 WAL SHA 一致，双节点签名通过，不授权 READY。
- Order P089 WAL：A/B 827,036 字节，SHA256 666a3c5073759f3e4a2e29765b4ad05a146c13f7adc96fbedd57a91b50b9ea82。
- Trade P246 WAL：A/B 22,495 字节，SHA256 425b18d2353545f0bd15b4797a04822ab9eef535733d485b92c6ccff726cefe5。
- tests/t190_readonly_cash_wal_projection_audit.py 已改为核验首三笔 CashIn 的不可变前缀，不再误将后来的 Newing 合法追加当作旧完整哈希失败。原 3 笔现金流水和余额对应真实 MySQL PASS。
- T199b Common JAR SHA256 a9838d6166aaf7d61ccf8662acb110011feb7b42a1a586c0dbceebc109b7e567，Order/Trade 镜像均同一 Jar。
- Common 原物理 runtime、Custody 与 Netty 相关 27/27 JUnit PASS。
- T199b 四容器实际滚动重建并启动：OrderSvrA/B、TradeSvrA/B 各自 Common/Gateway 注册正常；Order 两端热订单内存恢复到 664，物理原 WAL 未删。
- 范围说明：T199b 竞态修复后进行了真实冷重启与存储一致性复核；新增订单无重启副本实时 Apply 的 E2E 是在 T199 版本完成，不得混淆为 T199b 补丁后再次实测。

## 尚未通过 / 不得跳过
1. Robot.cancelBatchOrder 仍返回 ORDER_COMMON_DURABLE_COMMAND_NOT_CONNECTED；Trade 冻结资金释放、Order Maker 删除尚未接入已认证 CANCEL after-state，持续刷新报价 NO-GO。
2. Order -> MD 的 ORDER_MD_PERF_STATS 仍为 publishedOrderBook=0、publishedDepthDiff=0、stateBooks=0。内存存在 Maker 不等于 Web 真实盘口可见。
3. 真实撮合 tradeExecs=0，资金/持仓/委托/成交/Projection 全量一致尚无 E2E 证明。
4. 自动 SIGKILL A/B 主切、反向追平未验收；手工滚动替换不等于自动故障切换。
5. 既有历史 Newing 必须幂等处理，不能清空签名提交或重复 CashIn。

下一 P0：Trade 认证 CANCEL 资金/持仓/open-order/dedupe after-state，经 Common 签名提交，再由 Order Common STATE_REMOVE 释放 Maker、MD 推送 Diff；之后 10×10 Robot 多周期、真实撮合、MD Snapshot/Diff、故障互切完整一致性验收。

本轮没有调用 GitHub Actions、删除数据或伪造证明；完整 HA 仍 NO-GO。
