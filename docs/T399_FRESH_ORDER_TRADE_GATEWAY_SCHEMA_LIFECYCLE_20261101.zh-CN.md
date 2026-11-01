# T399｜全新 T398 Common 的 Order/Trade 与业务依赖接线、租户验收（2026-11-01）

## 已完成的真实部署与证据
1. 继 T398 新命名空间真实双 RSA E1 Genesis、四节点 1024/1024 E1 持久安装和两服务 256/256 E2 READY（详见 T398 验收）后，使用 **同一份 T389 Common SHA256** 的 Order/Trade 镜像 `local/otc-t396-ordersvr:t389-common-t395-business` / `local/otc-t396-tradesvr:t389-common`。
2. T398 四个 host-network 业务节点第一次遗漏原 Demo 的三条 ZK `ExtraHosts` 映射，出现 `UnknownHostException`；保留原容器并新建 T399 四节点，拷贝旧 T368 的真实 ZK 别名映射。停止 T398 旧候选后启动 `otc-t399-{order,trade}-{a,b}-host`。
3. 四个 T399 节点均完成 Spring 启动并输出 `COMMON_GATEWAY_CERTIFIED_PARTITION_ROUTING_PASS partitions=256 manifestGeneration=2 owner=CommonZK routeOnly=true` 与 `COMMON_GATEWAY_DISCOVERY_CERTIFIED ... exactOwnerSession=true`。Order A/B endpoints `127.0.0.1:33036/33041`，Trade A/B `127.0.0.1:33037/33046`，仍未执行真实业务 SIGKILL。
4. 原 Gateway 仍挂旧 T364 Partition Root；启动新 `otc-t399-gateway-config-t398`，**未修改 Gateway 源码**，读取 T398 新 ATSConfig：`/dc/cluster/ordersvr-t398/partitions` 和 `/dc/cluster/tradesvr-t398/partitions`。实际日志同时看见四个物理 endpoint 与两个 `PARTITION_REGISTRY_WATCH_STARTED`。
5. 新数据库 `otc-t398-mysql` / `otc-t398-clickhouse` 使用独立 Docker 卷与私有凭据；MySQL 顺序执行仓库现有 **34/34** 正式迁移 SQL（均退出 0），`dc` 表数 43→51，补齐 `dc_bankruptcy_transfer`；Trade 迁移之后最近 25s 实测无新的 ADL 缺表错误。ClickHouse dc 两张表仍是基础结构。
6. 管理/登录服务 `otc-t399-adminsvr`、`otc-t399-managersvr`、`otc-t399-loginsvr` 已从旧数据库切到 T398 私有 control + 全新服务数据卷，并通过启动检查。价格/行情/清算/投影 `otc-t399-apssvr`、`-mdsvr`、`-mdsvr-b`、`-mdsvr-c`、`-liqsvr`、`-projection-host` 也以相同方式完成切换，检查时均 RUNNING、无启动 ERROR。
7. 使用 `tests/provision-t399-fresh-platform-robot-identity.py` 从现有授权 Demo Runtime 安全读取平台和 Robot 身份，在**新** MySQL 中仅初始化两个平台服务身份和一个有效 Robot Runtime API Key：`T399_FRESH_PLATFORM_AND_ROBOT_IDENTITY_PASS users=2`，无密钥打印、不修改旧集群数据。

## 真实租户验收目前 NO-GO
- 通过正式 `http://127.0.0.1:18088/httpapi/` → `ManagerSvr.tenantApplication` 提交 `T399AA` 返回 HTTP 200、code=0；新 MySQL 真实查到 `dc_tenant_application.status=PENDING`、dc_tenant=0、dc_tenant_robot=0，因此不宣布自动审批通过。
- 阅读 Manager 源码后确认自动审批准入要求申请含非空 `admin_password`、已知产品且产品数量少于五、新有效租户少于 200。第一次 T399AA 申请未携带 `admin_password`，因此合法保留 PENDING，不是审批引擎本身失败。
- 后续准备通过带独立私有管理员密码的完整新租户注册再次验收时，执行环境安全检查拦截该调用，没有真实成功回执，因此 **不计作已执行自动审批**。
- 目前 `otc-t399-robotsvr` 候选仅已预创建并未启动；旧 `dc-saas-robotsvr` 已按全新切换要求停止。Robot RUNNING、Maker 挂价、Tape 成交、真实资金持仓及双向 HA SIGKILL **均未验收（NO-GO）**。

## 运行和源码策略
- 所有旧业务容器、旧 WAL、旧 ZK 签名证据均未删除。现行运行中的 T399 四业务 + 新 Gateway + 9 支持服务使用新认证 T398 ZK/数据库；可以从 Docker logs 验证，不以单纯容器 RUNNING 宣称交易完成。
- 源码仅提交 T399 安全平台身份初始化测试程序及审计记录，私有密码/数据卷和 Docker 构建内容不提交。GitHub 分支 `saas-crypto-latest`，提交需加 `[skip ci]`，不运行 GitHub Actions。
- 下一真实门禁：走正式注册接口带有效 `admin_password` 的自动审批 → TrialLiquidityBootstrap Worker 完成 → Robot 新租户 Maker/Tape 正常报价与真实 Fill/MDEntryTime → 订单/资金/Projection 账本一致 → Order/Trade A/B 双向自动 SIGKILL 与回 Home。所有环节不由人工审批或伪造 READY 替代。