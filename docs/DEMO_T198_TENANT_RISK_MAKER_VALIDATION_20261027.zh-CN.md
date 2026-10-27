# T198｜真实租户风控与 Maker 验证（2026-10-27）

状态：NO-GO。用户最终标准仍是新租户自动启用 Robot、持续盘口、真实成交及 Order/Trade A/B 自动互切并保持数据一致。

## 真实 Demo 结果
- Common、Order A/B、Trade A/B 都已启动与 Common Gateway 注册。Order A/B 真实带 660 条历史 E2 WAL 冷重启通过。并非自动主切验收。
- Trade SymbolCheck 旧代码只按全局产品代码查找；修复为 location + security_id 并对缺失 Admin querySymbol 快照作限频 60 秒的 canonical DB 产品有效性核对。有效查询要求有效租户、交易/产品/数据源启用、试用未过期、全局产品有效；数据库查询失败则拒绝。
- 本轮 1×1 档位、短时间 Robot 真实探针：Trade 风控成功批准两笔 Newing，回调 success=true、code=0；Order B 两笔 Newing→New，makerAdds=2，activeOrders=662；非真实成交。
- 之后在 finally 分支恢复 Robot 的 10×10 档位、200ms 原配置并关闭。数据库确认 enabled=0。
- Order P089 A/B WAL SHA256 都为 8b9fd693cbfeb20cc26c1761ec7e0e92dd5620ee244574681f61dfe5f5383160；Trade P246 A/B 都为 444b65742c0fa07d9d15c0ea2348b1c56bb9d4dfc80d10079ecae9991b783cc6。
- Trade SymbolCheckTenantScopedTest 1/1 通过；Order Common Maker 提交和 Trade 拒单回归通过。
- saas-crypto 本地源代码提交 Common=93c00c6、Order=a2e45ac、Trade=54081c9；未调用 GitHub Actions。

## 当前 P0 阻塞
1. Robot 撤单返回 CANCEL_FAILED / ORDER_COMMON_DURABLE_COMMAND_NOT_CONNECTED。不可使用旧的 mutate-before-WAL 撤单来绕过。
2. Order A 的业务内存仍有 660 条订单，而 B 为 662，虽有相同物理 WAL，备用节点尚未实时 Apply 已认证的增量。不可宣称业务状态一致。
3. tradeExecs=0；真实相向撮合/成交及 Trade 冻结资金释放、订单、成交、持仓多域认证提交通路尚未完成。
4. MD A/B 的真实盘口 Snapshot/Diff 未取得证据。
5. 历史 660 条 NEWING 需幂等终结或恢复。自动 SIGKILL 互切和反向一致性仍未验收。

## 明确下一步
- Common 负责仅对经过真实多节点签名且已持久化证书的连续 WAL 增量触发通用业务 Apply，防止副本仅存文件而内存落后；不得在单纯 WAL fsync 后提前 Apply。
- Trade CANCEL 先持久化保证金/持仓释放的认证 after-state；Order 再通过 Common 已认证状态变更移除 Maker，恢复 Robot 报价更新。
- CrossStrategy 全量撮合原子状态提交、MD Snapshot/Diff、最终新租户 E2E、真实 SIGKILL A/B 连续互切和余额/仓位/委托/成交/Projection 核对。

Demo 数据、证书和物理 WAL 全部保留，测试 Robot 保持关闭。没有宣布 READY。
