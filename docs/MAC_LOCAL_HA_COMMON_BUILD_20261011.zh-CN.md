# OpenTradingCore：Mac mini 本地 Common → Order/Trade/MD 联合构建与验证（2026-10-11）

## 策略

**开发期：本地编译；稳定后才批量发布 Central / GHCR。** Maven Central 可以作为第三方构建依赖的下载源，但不对外执行 `mvn deploy`。每一轮本地代码修改无需上传到 Central 或覆盖 `latest` 镜像。

- 机制层：`com.app.common` 负责复制协议、快照完整性/分片校验、恢复边界、归档回收判定。
- `com.app.dc` 显式依赖本地 Common 开发版本。
- Order/Trade/MD 服务使用各自业务状态的 snapshot installer/adapter；不复制通用机制源码。
- 此脚本编译 **common + com.app.dc + Order/Trade/MD**，生成三个镜像。**Gateway、Projection、Admin、Robot 等其他 Java 消费者还没有纳入这一轮的统一 Common 开发镜像**；不能把单节点金丝雀成功当成完整集群已升级。
- 真实自动 MD HA 仍需旧 publisher fencing + 当前 Order 全市场来源证明 + MD epoch 恢复 + Robot 对账；本地构建绝不绕过这些门禁。

## 一次构建（Mac）

设置五个源码路径，指向当前正在开发的工作树，而不是 origin 的过时提交：

```bash
OTC_LOCAL_BUILD_ROOT="$HOME/.opentradingcore/local-ha-validation-$(date +%Y%m%d%H%M%S)" \
OTC_COMMON_SOURCE="/path/to/com.app.common" \
OTC_DC_SOURCE="/path/to/com.app.dc" \
OTC_ORDER_SOURCE="/path/to/ordersvr" \
OTC_TRADE_SOURCE="/path/to/tradesvr" \
OTC_MD_SOURCE="/path/to/mdsvr" \
bash scripts/build-local-ha-demo.sh
```

脚本先把各工作树**连同未提交修改**复制到指定构建目录，但跳过 `.git`/`target`；源文件不会被修改。仅在构建副本中把 Common GAV 改成 `3.0.17-dev<common-sha>-SNAPSHOT`，再同步修改 `com.app.dc` 的依赖。使用 Mac 本地 `~/.m2` 缓存，缺少插件时可以从公共仓库下载**构建依赖**，但只运行 Maven `install`/`package`，不运行 `deploy`。

本地镜像基于已经缓存的 Temurin Java 8 Maven 镜像（**开发验证专用**），不会修改三个正式 Dockerfile；镜像打 `dc.build.kind=mac-local-ha-demo` 标签和 Common GAV/SHA256。与正式 GHCR 的 Java 8 JRE 基础镜像不同，正式发布仍按原 GitHub Actions 构建。

镜像及检验清单：`$OTC_LOCAL_BUILD_ROOT/artifacts/local-ha-images.env`。要求 Order、Trade、MD 镜像内只有一个 Common JAR，且三个 JAR SHA-256 逐位相等，不满足则拒绝构建成功。构建失败后可以在同一个根目录设置 `OTC_RESUME_BUILD=true` 重试**已冻结**源码，不自动删除旧证据。

## 2026-10-11 实际 Mac mini 验证

- 源 Common `f9a1b26`（公共恢复边界、SHA 校验、归档 fence）；独立开发 GAV `io.github.bliplink:com.app.common:3.0.17-devf9a1b26b-SNAPSHOT`。
- `com.app.dc`：本地 Maven install 成功；Order `6303989`、Trade `43e2f3f` + 工作区恢复校验改动、MD `bcdec88` + 当前工作区内容均成功编译打包。
- 三个镜像：`dc-saas/ordersvr:local-cf9a1b26b-20261011012559`、`dc-saas/tradesvr:local-cf9a1b26b-20261011012559`、`dc-saas/mdsvr:local-cf9a1b26b-20261011012559`，`linux/arm64`，内部 Common SHA256 **`719377fa7d223fa8559dbf2feca2ae835a235c7895128dc932b66ab7b0753c79`** 全部相同。
- 本地依赖下 Maven 全量测试：**Order 322（0 failed, 0 errors, 1 skip），Trade 214/214，MD 125/125**。另外公共包单独 124/124 PASS。
- 正常十租户环境仅对**无 Primary 分区的 MD-C**执行金丝雀更新，保持五个旧容器挂载路径、host network、640MiB 内存、0.35 CPU 不变。容器启动成功（0 重启）、新的 MD-C ZooKeeper ephemeral membership **在线**；256/256 MD 分区 READY，MD-A/B 仍分别 128 PRIMARY，无缺失恢复候选。主站及 Trade Web 均 HTTP 200。Order A/B/C、Trade A/B、MD A/B 均保持旧 GHCR 镜像，**没有进行全量 Demo 重置**。
- 本地镜像尚无正式发布审核，故 MD 预检查返回 `MD_NODE_UNHEALTHY_OR_UNREVIEWED:MDSvrC`，加上已有的四项权威快照/fencing/Robot 证明缺口，**decision=BLOCKED**。禁止把金丝雀启动成功当作 MD 自动 HA 的故障注入许可。此标记是预期的强校验，开发验证不放宽。
- 为避免正常环境定时拉取 GHCR 覆盖正在验收的本地 MD-C，已创建 `${HOME}/.opentradingcore/dc-saas-runtime-clean-20261010/auto-update.paused`；恢复所有生产镜像、确认镜像身份后再按原来的 `resume-saas-auto-update.sh` 安全流程解除。当前没有启用的系统定时自动部署计划，但保留显式保护。

## 接下来

1. **公共化闭环：** 把 Order 原有 SnapshotTransfer 与同 epoch rebase 调用切到 Common 适配接口；Trade 独立实现业务快照下载安装、SHA 验证和安装后无缺口追平；二者通过相同公共状态机管理 epoch/commit/GAP 及 GC fence。不能将仅供单元测试使用的公共判定类宣称为业务快照传输已实现。
2. **隔离数据环境完整回归：** 统一重编译所有实际使用 Common 的服务，使用本地镜像锁/配置清晰记录完整版本，重新部署 Demo，自动注册 10 租户并启动 Robot，再验证 Order/Trade 主备恢复与 MD 源端权威证据。
3. **只有通过后：** 收口镜像与中央仓库依赖版本并由 CI 发布正式 GHCR ARM64/AMD64 双架构镜像。

此前已触发的 `com.app.common:3.0.17` Maven Central 重试任务在本轮构建期间完成 SUCCESS（Actions 38101384099）；该任务来自此前的正式发布尝试。**本轮上述 dev 构建不依赖它，也不需要以后每次 common 改动都发布 Central。**
