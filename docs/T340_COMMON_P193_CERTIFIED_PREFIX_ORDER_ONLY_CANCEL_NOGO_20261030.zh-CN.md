# T339–T340｜ORDER_ONLY 撤单隔离 + Common P193 认证前缀候选（2026-10-30）

## T339：原产品级 ORDER_ONLY 撤单路径修复

- 上轮 T338 恢复产品级路由后发现：`OrderCertifiedCancelSaga` 批量撤单/补偿重试仍无条件调用 `TradeSvrClient.updateOrder`；它只适用于 `TRADE` 资金结算产品，不适用于 `ORDER_ONLY`。
- 在 **Order 自己的业务层**读取不可更改的 `matching_mode`，仅 `TRADE` 请求 Trade 原资金冻结释放与已签名去重；`ORDER_ONLY` 不调用 Trade，仍然走 **同一个 Common** 的 `Pending_Cancel` 和终态 `REMOVE` 持久化。未知模式在任何写入前拒绝。
- 已补测试：ORDER_ONLY 下纯撤单不调用 Trade，非法模式不写 WAL；原 T335 认证 Trade 撤单 / 部分成交尾单回归不改变。
- 本地 Order `saas-crypto` commit `a406056`，Maven 全量 **41 suites / 134 tests / 0 failures / 0 errors / 0 skipped**。此为业务代码测试，不代表现场 ORDER_ONLY E2E。

## T340：Common 物理签名认证前缀安全准备

- 原始 P193: Order A E2 原 WAL **22667** 完整条，Order B **22668**，B 最后一条原始 `STATE_REMOVE` 只有 CRC / fsync、**无 seq22668 正式独立提交证书**，不得当作已提交。
- 在 **Common 原有 WAL 类** `CommonFileBusinessWal` 添加 `stageCertifiedPrefixCopy`：仅允许原 WAL read-only 打开、独立 A+B RSA CommitIndex/累计 Custody 回执验证，复制精确原始认证前缀到不曾存在的全新目标文件，强制落盘；拒绝覆盖目标，保留原 A/B WAL 不变，绝不签发 ACK/READY。
- 用原始 Mac T330 P193 WAL + 原 A/B RSA 公钥 + Custody/Receipt 完成单测：新候选文件逐字节等同 A 原认证 22667 条，B 的未认证第 22668 条不会被当作成功或直接删除；原始证据不变。Common 4 套专项 **15/15 PASS, 0 skipped**。
- 本地 Common commit `57161f4`，分支 `codex/t177-common-saas-crypto-integration-20261027`。前置 T337 原 RSA 验证 commit `1af4847`。
- **未完成：** Common 仍未把带权威 ZK / 旧 Primary 实际撤权/冻结 / 新 Epoch 启动的前缀候选安全接线进在线恢复。没有替换在线 Order/Trade 容器，没对真实 WAL 截断、清空、清账、另造证书或强制 READY。没有实际运行 ORDER_ONLY、Robot 和 SIGKILL。Live E2E、A↔B HA 仍 **NO-GO**。
- 关键边界：Common 只处理不透明 `byte[]` WAL，Order/Trade 仍由各自业务状态机负责。不得为了修 P193 而引入 Order/Trade 特制 HA 或对第 22668 条未认证 terminal 付款 / 重放。

## 后续唯一 P0

1. 在 Common **现有**授权机制中，以真实 ZK Epoch/租约、old-owner fencing + 双签 CommitIndex/Custody 决定新的读写授权，不能仅因原始前缀验证通过就重开放旧 Epoch Writer。
2. 新的 Common 节点完成实物有锁 WAL / 已认证业务 Apply / Replica 完整追平，Common 自动 Watch / Spring 生命周期真实常驻并验证健康分区不被 P193 扩散。
3. 在这之后再部署 T339 Order 镜像、启动机器人、依次测 ORDER_ONLY 不动 Trade 资金、TRADE 部分成交剩余撤单、Tape/MD、自动 A↔B 与最终账本一致。
