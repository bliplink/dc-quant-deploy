# OpenTradingCore 最新代码归档｜saas-crypto-latest｜2026-11-01

## 用户确认的快速开发策略
Mac Demo 以快速发现与修复系统机制为第一目标。旧 Demo 数据、旧 WAL、残留分区、旧租户无法安全恢复或拖慢进度时，保留必要失败证据后优先独立新 namespace + 空数据全新部署，自动审批创建租户并验收 Robot 持续报价、Tape 成交、Order/Trade A/B 自动主切与资金/订单一致性。仍须使用真实 RSA/Quorum/READY 和 Common 认证，不能复用老 Epoch 签名或虚报 PASS。详见根目录 AGENTS.md。

## 本地源码归档（各仓库对应 saas-crypto-latest）

| 项目 | 工作目录 | 最新 HEAD | 说明 |
|---|---|---|---|
| 部署与验收 | dc-quant-deploy | 14e61d5（本发布记录提交前） | 更新 AGENTS、T397 virgin ZK bootstrap、T392–T394 验收证据 |
| Common | .work/t374-demo-common-ha | 065da2c | T389 认证 Common 候选所用源码分支；镜像 Common JAR 单独校验 |
| Order | .work/ordersvr | 00eaf33 | 认证撮合 Maker/Taker 成交时间写入业务 after-state |
| Trade | .work/tradesvr | 3a9c407 | Common-only 路由与业务现有代码 |
| MD | .work/mdsvr | 6ad0105 | 原执行 TransactTime → 最近成交 MDEntryTime 映射测试 |
| Trade Web | .work/dc-trade-web | fe09ea3 | iPhone13 最近成交时间与 MD 最新执行一致性处理 |

**注意**：这是六个独立 Git 工作目录各自的本地 saas-crypto-latest 分支，不是一个混合所有源码的大仓，也没有改写/强制覆盖 origin/saas-crypto。大量本机旧改动与本地环境配置未执行 git add .，没有提交二进制、凭据、数据卷、临时构建目录。

## T397 全新重建实际进度
- 全新根：~/.opentradingcore/t397-fresh-20261101-r1（原 T364/T365/T371 证据保留）。
- 两服务新 ZooKeeper namespace：/otc/t397-fresh-20261101-r1/order 和 /trade。
- 已生成并通过 Java 校验安装各 256 行新 E1 STRICT_QUORUM RECOVERING 清单，Home A/B 各 128，manifest 初始 version0，READY=0；尚未发布业务认证 E2 READY。
- 用新的 owner token 生成了四节点私有配置（仅留 Mac，本仓不收录）；旧 T364 signer keys 仅作为已有独立物理 RSA 身份，不能复制旧出生签名。
- T389 Common JAR SHA-256：6b4418f7b1373bb68a9fac4c79aa4406001e1699ec6d9dd080c83323110e2eae。T396 Order/Trade 镜像构建通过，但旧 Order B 对超大 E2 WAL 冷恢复 FAIL；全新部署用 T397 避免这批旧数据。
- 目前 T397 仅完成全新 namespace/配置/初始清单。**E1 双物理真实签名、四节点安装、E2 READY、Order/Trade 替换、Robot 实盘模拟成交、双向故障验收均尚未完成，NO-GO。**

## 后续顺序
1. T397 两服务四个物理节点独立 RSA E1 原始业务快照/零头 WAL Genesis，校验两个独立 lease 与完整 256 分区。
2. E1 INSTALL 256/256 x4、双签 E2 READY 发布后，使用同 Common SHA 的 Order/Trade 镜像连接新命名空间与空业务数据库。
3. 新租户自动审批 → Robot Maker/Tape 报价 → 委托成交 → MD 最近成交真实时间 → Order/Trade 双向自动故障切换，全部达到验收门禁后才能宣布恢复。

GitHub Actions 不运行。远端分支推送/同步状态必须单独核实，不以本地提交等同远端发布。