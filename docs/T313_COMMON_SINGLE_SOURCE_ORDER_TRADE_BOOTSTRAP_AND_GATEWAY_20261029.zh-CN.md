# T311–T313｜Order/Trade 移除业务私有 HA 启动流程，复用 Demo 的同一 Common

日期：2026-10-29。范围仅 Mac 本地开发工作树与 Common Java 测试；没有替换正式 Docker Order/Trade 容器、没有删除真实 WAL，也没有使用 GitHub Actions。

## 已实施源码

1. `com.app.common` 的 `CommonRecoveryOnlyProcess.CertifiedOriginalFleetStager` 接收经过**当前 Common ZK 会话认证的真实分区 Epoch 清单** `Map<String,Long>`；调用前仅允许认证的 fenced 业务镜像/双来源恢复交易，缺少任何一项停在 `RECOVERING`。OrderSvr/TradeSvr 主入口均使用相同的 `CommonOriginalE1FirstReadyActivation::activate`，删除各自额外实现的 E1-to-E2 staging 回调与早期 `*CommonOriginalE1BirthWiring`，不再由业务服务单独判断首次选主。
2. 恢复缺失的三份**公共 Common** 服务适配器（均源自之前同一项目的 Common 实现，而非搬回 Order/Trade 私有集群）：`CommonOriginalFirstReadyBusinessGate`、`CommonCertifiedGatewayDiscovery`、`CommonCertifiedGatewayRoutingProjection`。业务仍仅通过 Spring 注入业务快照/恢复回调。Common 负责旧 Epoch/READY/真实双证书/路由发布。
3. `CommonCertifiedGatewayRoutingProjection` 将原先固定 E2/v1 的只读路由投影改为依据**当前受 Common 认证的 ZK manifest**：支持后续新的 Epoch；版本化 CAS 更新旧只读路由，禁止较早 Epoch 回退及同 Epoch 不明换主。引入 Order C 等经过 Common 身份核对的节点，但投影仍然不是新的授权权威，实际写入都必须通过 Common Writer/ACK。
4. `CommonCertifiedGatewayDiscovery` 不能继续向其它 Docker 容器发布 `127.0.0.1`。新增显式 `advertisedHost`，拒绝 `127.0.0.1`、`localhost`、非法节点/端口、缺少真实 ZK Owner Session；同一主服务的业务 Spring 配置通过 `order.common.gatewayDiscovery.host` / `trade.common.gatewayDiscovery.host` 传给 Common，**具体可达 Docker 地址必须由部署模板提供，不能猜测**。
5. T310 已完成的本地 `PartitionRegistry`/独立 ZK 路由回退、缺 Common 默认 Primary、Order `NEW_ORDER` 专用集群准入、旧 `ClusterPerfProbeHandler`、旧 mutate-first WAL 逃逸路径均保持删除/拒绝；业务撮合和资金规则仍由 Order/Trade 业务状态机处理。

## 已执行验收及当前真实阻碍

- 最新 Common 全部新代码 Maven compile **PASS**；针对性 `CommonRecoveryOnlyProcessTest` + `CommonCertifiedGatewayRoutingProjectionTest` **PASS**（包括跨 Epoch 单调路由更新、非法/loopback 地址拒绝、未经认证的服务节点身份拒绝）。
- OrderSvr 主入口与最新 Common API 已完成真实 `javac` 编译；TradeSvr 主入口独立 `javac` 源码检查会展开大量 Lombok 业务依赖，不能替代完整 Maven 全量验收。
- Order/Trade 共 7 项架构测试此前已通过；本轮未执行正式服务 E2E 或机器人。
- **尚不能全量编译/替换 Order/Trade**：最新 `.work/com.app.dc` 与新 Common 版本一致，但未包含旧 `com.app.dc.security.ExistingDemoRsaNodeIdentity` / `CommonConfiguredNodePeers` 两个 Demo RSA 身份适配类；最新版业务主入口、多个签名业务回调还直接引用这两个名字。原来 T310 尝试迁移该认证适配器的源码时执行环境安全检查禁止。没有绕过检查、没有用弱身份模拟或关闭 Common 的真实证书门禁凑编译。
- Gateway 新的 `*.gatewayDiscovery.host` 属性需要随着本地新镜像 Compose 一起提供；未设或为回环地址应拒绝发布，而不是给 Gateway 一个不能访问的 `127.0.0.1`。
- Common 全量回归在后台最后一轮含 RSA key 的运行结果以后续测试日志为准；先前不传 RSA 时 148 suites/641 tests/585 pass/56 skipped/0 failed，不可把 56 跳过宣称已真实验收。
- Git 本地工作树有 T310 前已存在的用户改动，不能覆盖；本次新增和修改均仍为**本地未提交改动**，不宣称已推送到 GitHub。

## 下一步唯一顺序

先由平台允许的正式方式统一两项 Demo RSA 身份适配到 Common（只读现有密钥、严格物理 Key Pin 不变）；保证 **Common → shared business module → Order/Trade** 的全部 POM/类路径单一版本且两个服务全量本地编译回归。再对照一键安装脚本把原始 E1 Genesis 证据及 Gateway 非回环 Host 接线完全打通，先重新部署 Demo 的 Order A/B/C、Trade A/B（必要时只清理可丢弃业务新数据），新租户→Robot 报价及 Tape 点价→真实成交→自动双向 HA 全验收。**目前不能宣称最终 GO。**

## 2026-10-29 本轮最终本地提交与回归实测

| 仓库/分支 | 本地提交 | 结果 |
|---|---|---|
| `bliplink/com.app.common` 本地 `codex/t177-common-saas-crypto-integration-20261027` | `662a55d` | Generic E1 恢复/认证路由、动态新 Epoch、Gateway 非回环地址；**Common 全量 148 suites/642 tests/637 passed/5 skipped/0 errors/0 failures**，真实已有 Demo RSA 证书目录提供给 Maven，退出 0 |
| `.work/ordersvr` `saas-crypto` | `f504e0d` | 删除服务私有分区/旧 E1 重复接线与无效集群探针；边界回归 Order 4/4 PASS；OrderSvr 入口使用同一 Common 首次激活回调，Spring Gateway 适配源码单独编译 PASS |
| `.work/tradesvr` `saas-crypto` | `3ecc246` | 删除服务私有分区/旧 E1 重复接线与单机 mutate-first 回退；边界回归 Trade 3/3 PASS；Gateway Spring 适配源码单独编译 PASS |
| `.work/com.app.dc` `saas-crypto` | `e462d5e` | 三个项目 Maven GAV 锁定同一 Common t143/biz t313 版本，公共业务模块本地构建 PASS |

**上述均为本地 Git 提交，没有 GitHub Push/GitHub Actions，也没有把它们描述为线上上线。**

检查同版 Order/Trade 完整 Maven 后，当前第一个确定阻碍是 `com.app.dc.security` 包缺失：`ExistingDemoRsaNodeIdentity`、`CommonConfiguredNodePeers`。这两项不能降级为未经证实的字符串身份或假 RSA；原迁移操作曾受到执行环境安全检查，**不再尝试绕过**。新镜像/实际启动仍 NO-GO。Gateway 必须配置可从其它 Docker 容器访问的 `order.common.gatewayDiscovery.host`、`trade.common.gatewayDiscovery.host`，不能用 `127.0.0.1`。此外 Fresh E1 首次签名 Genesis、双副本物理恢复和业务自动 READY 仍须真实验收。
