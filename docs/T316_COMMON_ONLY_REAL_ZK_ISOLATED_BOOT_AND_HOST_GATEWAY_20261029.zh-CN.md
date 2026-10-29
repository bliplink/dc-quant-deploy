# T316｜Order/Trade 使用真实 Common RSA + 三 ZK 的隔离启动及 Host 网络兼容性

日期：2026-10-29。统一架构边界不变：Common 是唯一选主/WAL/复制/物理签名/快照/恢复/READY 权威，Order/Trade 仅实现业务状态机，不增加集群或交易功能。所有测试均在 Mac 本地操作，没有使用 GitHub Actions，没有修改正式业务容器。

## 真实启动证据

- T315 两个新业务镜像已经 `mvn clean package` 全量通过（Order 125/125，Trade 202/202，0 失败），统一 `com.app.common:3.0.22-t143` / `com.app.dc:0.0.6-common-t143`，MySQL 驱动 `8.0.33`。
- 对照正式 `dc-saas-ordersvr/tradesvr/gateway` 的 Docker inspect：三者**实际都使用 host 网络**。因此原正式发布 `Host:127.0.0.1,Port:*` 在当前宿主机网络模式合法，不能因为桥接容器的行为错误拒绝；其它网络模式必须部署者显式提供可达地址。
- 建立 `~/.opentradingcore/t316-common-only-isolated-20261029` 的单独配置/磁盘根目录，绑定原有 RSA A 私钥及可信公钥目录为只读，使用运行正常的真实 T84 三 ZooKeeper (`otc-t84-source-integrated-otc-ha-zk{1,2,3}-1:2181`)；将 **所有分区控制路径** 隔离到 `/otc/t316-20261029/order|trade`，所有持久数据写入本次专有目录。没有复制旧的 WAL/签名、没有伪造新 E1 创世票据；测试禁用 Gateway 服务发现发布，避免新旧节点注册冲突。
- 新 Order 镜像启动能够实际连接该 ZK 集群、进入 `COMMON_ONLY_CERTIFIED_BUSINESS_SPRING_NO_LEGACY_ZK_START`。首次由于空数据目录缺少真实 WAL 根目录被 Common 正确拒绝；只创建空的隔离目录再启动，越过文件挂载检查，但最终 `COMMON_CERTIFIED_CENSUS_STARTUP_TIMEOUT` / `Common authenticated node routing census not READY` 而退出 1。**这是缺真正的签名 E1→READY 认证分区清单，不是可以关闭的校验**。
- Trade 使用相同独立 RSA/三 ZK 及隔离数据目录；在桥接网络与正式 host 运行模式不一致时，MySQL `127.0.0.1` 会连接拒绝，后续 Spring 依赖初始化也被相同的 `COMMON_CERTIFIED_CENSUS_STARTUP_TIMEOUT` 正确挡住。不能把这次隔离启动冒认成 Trade 业务 READY。
- 从 ZK1 只读检查 `/otc/t316-20261029/order/manifest` 与 `/otc/t316-20261029/trade/manifest`，均返回 **Node does not exist**，证明没有把未签名分区强行发布 READY。两临时测试容器完成后删除；正式 `dc-saas-ordersvr`, `dc-saas-tradesvr`, `dc-saas-tradesvr-b` 保持运行，原 Order B/C、Robot 保持停机状态，没有触碰旧 WAL。

## 最小兼容性修复（不是新功能）

之前 Common 的 `CommonCertifiedGatewayDiscovery` 要求显式发布地址，但无条件禁止 `127.0.0.1` / `localhost`。这一限制与实际 `host` 网络部署冲突：成功认证 READY 后仍会拒绝正式 Gateway 注册，属于部署约束误判。现移除**无条件回环地址禁令**，继续保留非空合法地址、精确 Order/Trade 节点 ID、Common 原 ZK 会话、物理 Ready、业务恢复 Ready、临时节点归属、幂等及 Epoch CAS 的全部原认证校验。地址是否跨容器可达由部署网络配置保证。既有桥接环境仍应配置非回环地址。

- Common 本地提交：`53bf6d4 fix(common): preserve explicit localhost Gateway endpoint for Docker host networking`。
- Common 定向测试 **PASS**，完整 RSA 回归 `148 suites / 642 tests / 637 PASS / 5 skipped / 0 failures / 0 errors`、Maven Exit 0。Common JAR SHA256 `ddd258df94449588d66593a05f5c201d16be64946605ec22cdc80e7f5f239150`。
- Maven local `install` 之后 Order/Trade 再次执行完整 `clean package dependency:copy-dependencies` 均 PASS，各 runtime classpath 仅一份 Common；镜像中的 Common JAR 与上述真实 SHA256 完全相同。
- 本轮新构建镜像：`local/otc-t316-ordersvr:common-host-verified` (image SHA256 `e53072fbf23bcf66efb66442eabc4fbe042ca3db4e7d36cdd722e585fdbd8efe`) 和 `local/otc-t316-tradesvr:common-host-verified` (SHA256 `9c7f35aa0a0327c258bfac4d1f4991fc6f0bae148850ace7b61d000c7e385d81`)；**两者仍是 `dc.release.gate=NO-GO`, `authorized=false`**。

## 下一项明确门禁

使用**现有 Common 首次 E1 创世/原始双 RSA 物理空 WAL 审核/全部 256 分区签名票据/共同 ZK 会话**，在同一隔离环境完成 E1→READY；不能把现有正式集群的旧签名票据复制到不同 ZK namespace。当前旧 firstboot 脚本配置与新 Common 认证阶段有差异，需核对并复用已实现的正式接口，而不是新写 Order/Trade 私有初始化器。然后在有隔离 MySQL 等依赖的环境正式启动两个业务服务，最后才替换 Demo，跑 Robot 报价/Tape 点价/真实成交和 A/B 自动互切、一致性核验。

**状态：真实三 ZK 联通与安全拒绝通过；签名创世、Order/Trade READY、Robot/成交/自动 HA 仍 NO-GO。**
