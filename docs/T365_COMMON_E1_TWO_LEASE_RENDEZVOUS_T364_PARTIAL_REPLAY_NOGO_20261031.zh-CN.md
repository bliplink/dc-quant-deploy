# T365｜Common E1 双节点冷启动租约会合与 T364 证据（2026-10-31）

## 结果与边界

Common 本地 commit **9561b74**。正式 E1 RECOVERING 业务安装前新增控制面 `CommonOriginalE1LeaseRendezvous`：每个节点先验证它自己由 Common 控制的 RSA/ZK 初始恢复租约，然后最多等待 60 秒、每 150 毫秒检查对端是否以**不同 ZooKeeper Session**持有活着的 ephemeral lease，只有两个租约都存在才进入原有业务恢复。启动竞态不会再让 A、B 先后因为对方还未登录而双双退出。超时、ZooKeeper 断联、自己失权、对端与自己共用 Session 均拒绝。

**这只是控制面协作，并不授予 READY。** 进入 E1 持久恢复后，每个分区依旧逐步重验原双 RSA Genesis、真实原始零 ACK WAL/Custody、Manifest 身份、两个 lease 的原有物理会话、ZooKeeper CAS 和业务回放。Common 之外 Order/Trade 不实现任何额外集群算法，也不让 ZooKeeper 进入 WAL 热路径。

已新增 `CommonOriginalE1LeaseRendezvousTest`：7/7 单测通过；覆盖稍晚才出现的物理 B 租约、对端一直缺席、ZK 失联、同 Session、伪造自己的 token、本地 grant 被撤权、错误 namespace 或无界超时。完整 Common 回归以最终 Maven 退出码为准，随后执行本地 Order/Trade 源码兼容性回归。

## 当前真实 T364 事实（不可冒充完整恢复）

- 独立真实三 ZooKeeper 上 `/otc/t364-fresh-20261031-r1/order|trade/manifest` 仍为 version0、generation1、256/256 E1 STRICT RECOVERING、READY 0。
- Order/Trade 各有 256/256 份真正 `CommonCertifiedGenesisQuorum.sealAndVerify` 的原始物理双 RSA 认证，共 512 个分区 Quorum / 1024 份原始物理签名；Home P000–P127 A，P128–P255 B。
- 真实独立目录 `~/.opentradingcore/t364-fresh-20261031-r1/data/OrderSvr/OrderSvrB/tx/P000..P003` 下，四个 Ledger 分别记载 `REPLAY_COMPLETE`。但 **Order B 仅 4/256；Order A 0/256；Trade A/B 各 0/256**。不能因为 P000–003 Ledger 完成就宣布服务或 128 Home 的整体 READY。
- 上次恢复进程因 `COMMON_FRESH_E1_ORIGINAL_VOTER_NOT_LEASED` 失去对端独立租约而失败，随后批量 Docker 启动受到执行环境安全拦截。因此本轮没有重启这批残留进程，不覆盖已签名的出生凭据，不修改原 T330 P193（A=22667/B=22668，有 1 条未认证尾部）。
- 原 Docker Demo 仍是 Order T335、Trade T336，Robot `Exited(143)`，**真实新服务和 Robot 均未恢复，整体 NO-GO**。

## 符合安全边界的实际恢复流程

1. **T364 已存在部分业务事务，不能当作全新零 Ledger 做删除后重签。** 若用 T364 续跑，必须由 Common 带真实同一原始快照、HEAD、ZK 双租约、证书与匹配的持久 Ledger 做认证续跑；若实现不具备该资格，应该在受支持的环境中使用**完全不同的新命名空间和新的原始业务 WAL 出生根**，如 T366，而不是复用 T318/T364 的 E1 签名或人为篡改 Version。
2. 新 E1 四个真实恢复服务要用 Common `RECOVERING` 原路启动，**A/B 两个独立物理节点同时保持存活**。新的会合点控制冷启动先后，已认证业务安装完成后服务继续保持租约，不应以“一次性运行完立即退出”的方式导致对端失权。
3. 两个独立节点对每个服务都需要各 **256/256 的 `DurableRecoveryInstallLedger.REPLAY_COMPLETE`**、双方真实原始零 ACK 签名，才可通过 Common 原始 `CommonOriginalE1FirstReadyActivation` 第一次 CAS 发布 E2 256/256 STRICT READY。
4. **控制面 E2 READY != 真实订单和成交可用。** 其后替换 Order/Trade 服务镜像，验证真实 ZooKeeper 注册、Gateway 自动连接、新租户自动审批、Robot Maker/Tape 自然报价、真实交易成交、Order/Trade SIGKILL 双向主切和全部 Home 128/128 归主耗时以及资金/委托/成交一致性。
5. 期间不恢复旧 P193 不可信尾部，不为让 Robot “亮绿”而关闭任何证书核验、不改变 Gateway 透传架构、不使用 GitHub Actions。

**本轮如果只有单测和预构建镜像通过，仍然判为 NO-GO，不把已有 Robot 容器状态当作真实成交证据。**
