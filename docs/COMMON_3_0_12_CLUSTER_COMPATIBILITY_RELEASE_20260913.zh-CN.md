# Common 3.0.12 集群兼容发布记录（2026-09-13）

> **历史发布快照说明（2026-09-19）**：本文记录 2026-09-13 的兼容性发布。当时的 gateway-api 版本和镜像组合属于该次发布证据；当前主线已使用 `com.app.common:3.0.13`、`com.app.dc:0.0.4-SNAPSHOT`、`gateway-api:3.0.6`，完整本地构建还固定 `gateway-api-java-v3.0.6` tag。不要用本文旧版本号覆盖当前 POM/构建脚本。

## 发布结论

- `io.github.bliplink:com.app.common:3.0.12` 已发布并可从 Maven Central 下载。
- `io.github.bliplink:gw:3.0.12` 已发布并可从 Maven Central 下载。
- 正式 GW wrapper 已升级为 `gw-app:3.0.10`，依赖 `gw:3.0.12` 与 `gateway-api:3.0.5`。
- OrderSvr、MDSvr、GW 的镜像供应链标签均为 `com-app-common-v3.0.12`，内置 Common JAR SHA-256 均为：
  `e447480cb7ca01097e18afff7a470bdd72d770f6a823aba6b70d433a3a895438`。
- ProjectionSvr、TradeSvr、LiqSvr、LoginSvr、APSSvr、RobotSvr、AdminSvr、ManagerSvr 的目标镜像也已逐个检查内置 JAR；哈希与上述值一致。
- ManagerSvr 首个目标镜像曾命中污染的 Maven 缓存，已拒绝上线。工作流现会删除指定 Common 版本缓存、从 Central 重新解析并写入镜像来源标签；修复后的镜像已通过检查。
- 生产 Placement 开关仍保持关闭，现有 legacy assignment 未被改写。

## 目标镜像

| 服务 | 目标标签 | 生产机镜像 ID |
|---|---|---|
| GW | `sha-0807d21` | `sha256:5dcf898fdaafe398ed4467543bd6c5b7e5781fc632a86a0df968951a9fa75512` |
| OrderSvr A/B/C | `sha-135eb32` | `sha256:4aec3c83236688507d501c504ce0d8316fa07226a760e45f317b4722a13c3425` |
| MDSvr A/B | `sha-5e8710f` | `sha256:93d8cdab0d4bd2b13ebf734b8762cba893c8177dc981adbddced11a53baadeca` |
| ProjectionSvr | `sha-92a2f52` | `sha256:117ea9e634aee3654b235fad9520f898527137ebdcf9257cd31df5fc072b6383` |
| TradeSvr | `sha-9c292ff486a71376ec1a950d4ef8671f85d44d79` | `sha256:baabc868e3db2f28589d9be4446f7d7d70cdf02e5eb9a4b97a211cd37985e318` |
| LiqSvr | `sha-105cdfbd2becc6e9187d8c42b2dc3c827ba268ed` | `sha256:dc43e22721e2c46b446d82af42b294bef172a2ffcec692c20622069c10774939` |
| LoginSvr | `sha-88d466d` | `sha256:2f0891ae824e568036c4b9285cea93572122efc840dcf5456174575877a58073` |
| APSSvr | `sha-c9f1376` | `sha256:8fff7b2035e808396bdb848ba3ce9ac13edf598379d96bc5d51dfc52cbf0e727` |
| RobotSvr | `sha-fd12103123ba169a0dac1893eec9b61928c49586` | `sha256:f04c92d5cc0136dc68cb6f27af67bf66fb336fce7e51c806c9d09a43831aad9f` |
| AdminSvr | `sha-06cf3d3a30bbcf277c837d84936f99d1f63e30b2` | `sha256:353a685aa6dfbcb743cd8c1dec78f59583bedea54f2b720a8da2c77e79d873a5` |
| ManagerSvr | `sha-517b6c0d53a2f2a39b6b1f8101717844f31b09f0` | `sha256:8bf5918e5200c356aeb2966cf0721f617c751759916827f9fc310d2854bdb311` |

上述镜像已预拉取到生产机。原运行镜像已在生产机打本地标签
`rollback-pre-common-3.0.12-20260913`，用于本批次快速回退。

## 已上线范围

- ManagerSvr 已升级到修复后的目标镜像。
- 端口 `33039` 正常监听，容器 `running`、重启计数为 0、`OOMKilled=false`，启动后没有新增 ERROR/Exception。
- 交易核心 GW、OrderSvr、MDSvr、TradeSvr、ProjectionSvr、LiqSvr 尚未切换，现有交易链保持运行。

## 核心滚动发布前置条件

当前 MDSvr A/B 各自承担一半 primary。直接逐台重启会让对应一半分区在重启窗口不可用，因此不得直接执行普通 `docker compose up`：

1. 先启动 MDSvr-C，但保持 Placement 关闭。
2. 以 learner 身份把 C 加入现有 legacy assignments，不能改变现有 primary，也不能覆盖并发 assignment 更新。
3. 等待 C 对全部活动 `location + marketIndicator + securityID` 生成当前 epoch 的完整本地行情，并验证它仍不发布。
4. 将待升级节点的 primary 分区迁移到已就绪节点，确认单发布者和 WebSocket 序号连续后再重启该节点。
5. 逐台完成 MDSvr A/B/C，再按 OrderSvr fenced recovery 流程升级 Order A/B/C 与 Trade/Projection。
6. 最后切换 GW，并运行分区、路由、历史查询、Robot、真实浏览器行情和下单验收。
7. 整批稳定后才允许进入 namespaced assignment 预置；`PlacementEnabled` 仍不得直接打开。

