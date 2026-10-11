# Mac 本地 Common / Order / Trade / MD 编译与 MD-C 真实金丝雀验收（2026-10-11）

## 执行范围与源码锁定

用户明确：Demo 旧业务数据可清理，不要求跨发版迁移；但本轮执行前**并未完成受支持的全新镜像发布/冷重部署入口**，因此先在现有 `dc-saas` Mac 环境执行独立 Common 版本编译、业务回归与 MD-C 金丝雀，**不将旧 Order/Trade Primary 直接滚动重启**，不触碰 MySQL 业务数据、Order CQ WAL。

Mac 本地隔离源码：`~/.opentradingcore/local-ha-fresh-20261011-1438/source/`，原源码均通过已提交源码检查（允许 `target/`）。构建脚本：`scripts/build-local-ha-demo.sh`，使用 Mac Docker Maven Java8，未发布 Maven Central/正式 GHCR。

| 模块 | 源码 commit |
|---|---|
| Common | `ffd928cc3be8` |
| com.app.dc | `2fa804757c56` |
| Order | `239f765ee325`（验证分支） |
| Trade | `0ad5191b8841`（验证分支） |
| MD | `bcdec888a847` |

独立 Common GAV：`io.github.bliplink:com.app.common:3.0.17-devffd928cc20261011065003-SNAPSHOT`。三个镜像内 **同一 Common JAR SHA256**：

`f2428e3e1cffa91a6dee7812d2d4483d00e458405883197269a1e32d500b5403`

构建成功的 Mac/Linux ARM64 本地镜像：

- Order `dc-saas/ordersvr:local-cffd928cc-20261011065003`，image ID `sha256:006bc371bf2cb711...`。
- Trade `dc-saas/tradesvr:local-cffd928cc-20261011065003`，image ID `sha256:648fa5d2c1a7f518...`。
- MD `dc-saas/mdsvr:local-cffd928cc-20261011065003`，image ID `sha256:019cbfb62af4e037...`。

## 全量回归

针对**本次镜像隔离源码**重新用 Maven8 跑全量测试：Trade **249/249 PASS**；MD **125/125 PASS**；Order **337 tests、0 failures、0 errors、1 skipped**。Java 测试日志在 Mac `/tmp/otc-fresh-1438-<服务>-test.log`。这些不是旧镜像测试结果。

## 本轮真实部署：MD-C 金丝雀

用本机现有 Compose 元数据和唯一 `dc-saas` 项目，明确指定`MDSVR_IMAGE_REPOSITORY=dc-saas/mdsvr`、`MDSVR_TAG=local-cffd928cc-20261011065003`、现有 `DEPLOY_ROOT`，`docker compose ... --profile md-cluster-c up -d --no-deps --pull never --no-build mdsvr-c`。

**结果：`dc-saas-mdsvr-c` 已实际 Recreated/Started；后续 `docker inspect` 返回 `running`、`RestartCount=0`，确认为本地新 MD 镜像。** 当前 Order A/B/C、Trade A/B、MD A/B 仍保留旧 GHCR 镜像；**没部署新 Order/Trade Primary，也没执行冷重置或切主**。

更新后 MD HA 只读预检查：**256/256 分区 READY、0 UNREADY；MD-A/MD-B 分别 128 Primary；`decision=BLOCKED`**。未满足安全门禁：MD-C 本地未审镜像、Order 最新权威完整市场镜像、MD 提升后全镜像、fencing/CAS、Robot 对账。任何自动 promotion/SIGKILL 仍禁止。

两个公开入口 HTTP 200：`https://opentradingcore.com`、`https://trade.opentradingcore.com`。

### 十租户与 Robot 只读验收

`tests/check-tenant-ramp-readiness.py` 两次实测：
- Mac 同时进行 Maven 全量编译测试时：`gate=NOT_READY`、`CPU PSI=29.02%>25%`；10 tenants 均有市场活动，10 Robot 均健康，472 market rows/5min。
- 编译测试完成后：`gate=BASELINE_READY_ONLY`、无 blockers、`CPU PSI=22.14%`、10 tenants、10 healthy Robots、500 market rows/5min、无 180s Order recovery signal、Order B 三秒采样 Full GC 0。**该指标不是订单 TPS 或 200 租户承载力证明**。

## 为何尚未冷重部署 24 个服务

`scripts/mac-saas-reset.py --mode plan` 返回 24 个 dc-saas 容器的 READ_ONLY 计划，P246 独立证据已验证、不会删除；`deploy-saas-macos.sh --check --full-cluster` 通过 Compose 静态校验。实际 `deploy-saas-macos.sh` 会强制套用 `release/saas-crypto-images.env`，当前 Order/Trade/MD **仍锁在旧 GHCR**。清空后用原一键入口部署会装回旧程序。该不匹配已经由 `scripts/check-demo-release-source-lock.py` read-only 检出。

另外真实 Order rolling HA preflight 仍为 BLOCKED：缺少 write drain、live durable replica watermarks、Projection watermarks、rollback plan。**不允许为了立即部署本地镜像而绕过正式发布锁/跳过 HA 安全门禁**。用户确认可丢失旧 Demo 数据 ≠ 允许自动让当前 Primary 进入不一致状态。请先提供/实现正式受支持的 Mac DEV 完整冷部署模式，其明确使用本地 manifest 并完成资源与安全预检查，或者统一发布 GHCR 版本并更新正式锁；然后才可进行全新十租户验收。

## 结论

- **已完成**：本地提交源码构建三镜像，同版 Common SHA，三服务 Maven 回归，真实 MD-C 金丝雀，新镜像 running/no restarts，现有十租户/Robot 只读健康验证及 MD HA fail-closed。
- **尚未完成**：24 容器全新冷部署、正式新 Order/Trade/MD 全集群上线、从空数据注册十租户、HA 真实故障注入与 200 租户压测。
