# T335–T336｜部分成交剩余量撤单、签名杠杆资金释放与 P193 未认证尾部（2026-10-30）

## 业务代码与代码回归
- Order saas-crypto 本地提交 030b23e：Partially_Filled 仅在 originalQty - cumQty = exact positive remainder 时进入现有 Common 签名 Pending_Cancel → Trade 认证 release → Common 签名 REMOVE；不改 Common/Gateway。Order Maven 全量 40 suites / 130 tests / 0 failures。
- Trade saas-crypto 本地提交 73b950b：Trade 以持久化原始 OPEN_ORDER 的 cumQty/leavesQty、price/qty 与 Order Terminal 回执逐项比对；只释放 leavesQty 的预留资金与手续费，不影响既有持仓；使用原始已签名 Position.leverage 而非查询时可能已改变的产品配置。Trade Maven 全量 52 suites / 207 tests / 0 failures。新增 current leverage=1、signed original leverage=10 情况下只释放原预留及未持久化原杠杆拒绝等单测。
- 真实资金根因：SWUUDO/WGOAVT 当前 MySQL dc_users_symbol_config.leverage=1，但 Trade A/B 物理 WAL 中原 Position.leverage=100，且 freezedMargin=freezedVolume/100。原 Trade cancel 重新用当前配置计算冻结，抛 TRADE_CANCEL_INSUFFICIENT_FROZEN_accountMargin；T336 已改为签名原杠杆，代码测试通过。

## Demo 实际部署与门禁
- T335 本地镜像 local/otc-t335-ordersvr:partial-cancel (sha256:4476ce9c1fd1a9720102648b202f49ab3f69c46250b6547f45654b929d1bb6ce)、local/otc-t335-tradesvr:partial-cancel (sha256:231147403ff3e820948ad203d3b230b61c71b006f9a9effa147606da664cb683)。先停 Robot，Order A/B 与 Trade A/B 均逐分区 256/256 CRC+WAL 完全相等，然后 Trade B/A、Order B/A 分批安全替换，均 Common 认证注册、Trade 2/2 内部连接、零重启循环。
- T336 本地镜像 local/otc-t336-tradesvr:signed-leverage-cancel (sha256:b14c0350c661d355ae9849b43f6346628811a5001e18ed178a75635c4f1d3140)。Trade B/A 滚动重建，继续原已签名 WAL 并通过冷启动认证；Order B/A 又受控重建以修复内部 TradeSvrClient 对旧进程的 TCP 连接。两端 Order 的 Trade 2/2 连接重新认证成功。Gateway 曾重启并重新发现所有正式服务，不改 Gateway 代码。
- 当前容器：Order A/B T335、Trade A/B T336、Projection T334 均运行，Robot 刻意停在 exited，防止 P193 非 READY 条件下扩大待结算写入。MD 的最近成交/Kline 尚未通过。

## 当前真正阻塞（不能标记 GO）
- Order 原始 WAL 的 P094 等其他 255 个分区字节完全相同；P193 B 是权威 Primary、A 是 Replica，两份物理 WAL 的共同前缀完全一致且各自 CRC/序号正确，但 B 第 22668 帧比 A (22667) 多一条完整 STATE_REMOVE。
- **不可把完整 CRC WAL 帧当成已提交**：B P193 的物理 commit-index 最新只有 commit-00000000000000022667.bin，尚无 22668 独立双签物理证书；A 已有共同历史 22667。ZooKeeper P193 READY 只证明控制面路由存在，不证明脏尾可写。Common 实际拒绝 `Common physically certified partition writer unavailable: P193`，保护有效。
- 原 tests/verify-t328-signed-order-ab-wal-readonly.py 只允许 A 领先，因此把 P193 B 领先错误标作两份 WAL 分叉。本轮修正为双向前缀判断；真实 B 领先一条返回退出码 2（NO-GO，noTruncation/noBusinessApply），而非误报两份已认证记录冲突。该检查**只读**，没有修复或推进签名水位。
- Common 原始源 `CommonFileBusinessWal` 明确保留并拒绝未认证尾部；`CertifiedDirtyTailBoundaryGuard` 目前只在测试里调用，没有可直接启用的生产修复入口。因此**未截断、复制覆盖或清理任何真实 WAL/CommitIndex、未强制恢复 READY、未绕过安全检查**。必须实现/找到经过原始物理双签、尾部封存、租约/路由冻结、授权恢复的 Common 正式事务，或者在新的、完全独立已认证 Demo Genesis 与全新账本上重新从零验收，而不是将现有簇不一致数据直接清除。
- Robot SWUUDO/WGOAVT 在最后一次恢复前曾 ERROR/0 单（旧 partial cancel 及 financial mismatch）。T336 重新启动后新的账户资金恢复仍受 P193 物理不可写阻塞；未证实 Robot 正常持续报价或 Kline。订单成交 E2E、Kline/MD、自动 Trade/Order A↔B 主备互切仍 NO-GO。

## P193 最后未认证 REMOVE 对应的独立金融证据（只读验证）
- 读取 OrderSvrB P193 的第 22668 条完整 CRC 原始帧，发现 `STATE_REMOVE` 对象 OrderID `1565783807729143808`，租户 `WGOAVT`、用户 `000200000001`、Qty `0.0003`、CumQty `0.0002`、剩余 `0.0001`。该帧 B WAL 有但无第 22668 份 Common CommitIndex 证书，**不能作为已提交 Order Terminal**。
- 读取 TradeSvrA P022 原始 WAL，该订单已存在 `CANCEL_OPEN_PREPARED`、Trade 物理 seq `8838`，并确认真实 `commit-00000000000000008838.bin` 已签名认证；两份 Trade A/B WAL 内容一致。因此 **Trade 已认证释放剩余冻结，但 Order 尚未完成最后认证 REMOVE**，是跨服务 Saga 的可恢复中间状态，不是可以再次退款的失败订单。
- Common 必须先封存/校验未认证 B WAL 尾部及签名物理 HEAD，再使 Order 读取原已认证 Pending_Cancel，调用 Trade **已有已提交的去重结果**，只补最后一个 Order 签名 REMOVE。不可将旧 seq 22668 的未认证 frame 复制给 A 当成财务成功；也不能重放第二次资金释放。

## 下一步严格顺序
1. 已完成只读核验未认证 OrderId 与对应的 Trade 正式 CommitIndex 8838；继续核对 Trade 去重回执及 Order Pending_Cancel 签名边界，确保金融释放绝不重复。
2. 通过 Common 原有恢复边界实现严格校验/封存/恢复到已经独立认证的物理 22667；未核验不得动 WAL。
3. 两副本重新认证并满足 READY 后重启原 Robot，确认剩余量撤单、财务不变式、报价和 Tape/MD Kline；最后注入真实 SIGKILL 测 A↔B。
4. 禁用 GitHub Actions，采用本地编译/镜像；本地 Git 源码/部署记录，不以未发生的远端推送声称完成。