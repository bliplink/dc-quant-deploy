# T321｜Order/Trade 隔离注册中心修正与四节点二次启动实测（2026-10-30）

## 结论

**T321 新隔离四个 JVM 的 Spring 启动、测试专用 ZooKeeper 注册中心连接、Common Netty TCP 可连接和每节点 256 个 E2 物理 WAL 均 PASS。正式 Order/Trade 和无人值守严格 2/2 HA 仍 NO-GO。**

- 分支：`bliplink/dc-quant-deploy` 本地 `saas-crypto`；Common 与业务镜像保持 T319 同版，没有改动 Order/Trade/Common 源码、认证逻辑、签名 WAL 或 ACK 策略；不使用 GitHub Actions。
- 诊断发现 T319 桥接网络 `otc-t84-source-integrated-net` 复用正式 Demo 只读 `/srv/dc/control/ATSConfig.ini`，其中 `REGISTER.Svr1.Host=127.0.0.1:32181`。这属于旧共享 `GwClient` 的服务发现注册中心，不是 Common 的 HA ZK。容器内 loopback 不通，造成 `ZkTimeoutException`；不能因此修改 Common 已认证的三 ZK 选主与水位机制。
- 仅在 Mac 本地隔离目录 `~/.opentradingcore/t319-business-ready-20261030/control/ATSConfig.t321.ini` 创建权限 **0600** 的测试专用配置。它复制正式格式且只将 `REGISTER.Svr1.Host` 指向同一 T84 隔离三 ZK 中的第一个节点 `otc-t84-source-integrated-otc-ha-zk1-1:2181`。该地址属于 **测试用旧业务服务发现**；Common 控制面仍继续使用已有配置中的三个 ZK 地址。
- 为避免修改正式共享 `ATSConfig.ini`，保留原 `otc-t319-order-a/b`、`otc-t319-trade-a/b` 容器为 **stopped**，逐台将同一测试数据根、只读 RSA、原 Common 镜像与相同环境原样用 `docker create` 重建为 `otc-t321-order-a/b`、`otc-t321-trade-a/b`，只增加额外 **只读覆盖挂载** `/srv/dc/control/ATSConfig.ini`。正式 `dc-saas-*` 容器和配置没有修改，也没有删任何旧 WAL。

## 真实运行证据

| 测试节点 | Spring Started | 测试 Registry | 当前 v4 E2 WAL | Common TCP |
|---|---|---|---:|---|
| `otc-t321-order-a` | 6.789 秒 | `SyncConnected` | 256 | `45322` OPEN |
| `otc-t321-order-b` | 8.134 秒 | 注册中心无新超时 | 256 | `45323` OPEN |
| `otc-t321-trade-a` | 9.792 秒 | 注册中心无新超时 | 256 | `45222` OPEN |
| `otc-t321-trade-b` | 8.844 秒 | 注册中心无新超时 | 256 | `45223` OPEN |

- 四个新进程持续运行；最后一次检查的 90 秒窗口每台新 `ERROR` 均为 0，已在测试容器内读取到正确的 `REGISTER.Svr1.Host`。
- 从 `otc-t321-trade-a` 实际发起 4 组 TCP connect，全部 OPEN。**TCP_OPEN 仅证明有活着的监听端口，不是业务 WAL 的持久 ACK/成交。**
- WAL 计数仅统计活动的 `t319-ready-v4` 目录，各 256；Order A 总历史目录还包含之前 `v2/v3` 构建测试产物，绝不可把全目录 769 当作活动 WAL 或新分区。
- 在隔离 `otc-t319-mysql` 查询 `dc_bankruptcy_transfer`、`dc_adl_execution_v2` 均成功，当前各 0 行；没有修改正式 MySQL。
- 增加只读自动核验脚本：`tests/verify-t321-isolated-boot.sh`，复核运行态、启动标记、独立注册中心、256 文件、最近 60 秒错误和真实 4 TCP 端口；**不创建新租户、不发起交易、不注入故障，也不宣称这些项目 PASS**。

## 下一步 P0/P1 门禁

1. Common **严格 `QUORUM_DURABLE`** A→B→A 自动 READY 全闭环仍缺：现有 T300–T308 的严格 recovery/READY 是多 JVM 真实原始 RSA 证明、但恢复完成步骤仍由验收脚本显式调用。仅能在 Common 的常驻 `CertifiedRecoveryCompletion` 生命周期复用既有审计凭据/证书/安装/READY；不得让 Order/Trade 另造集群。
2. T321 仍没有 Gateway/Robot/MD/APSSvr 的完整隔离业务链，故**注册自动审批、报价、Tape、真实成交与持仓/余额一致性均未验收**；此状态不允许把 T321 四个容器直接替换正式 Demo。
3. 正式 `dc-saas-ordersvr` 因 `receipt ledger head != physical custody` 重启频繁，本次读取时 `RestartCount=145`。它与 T321 独立测试数据无关，正式 B/C/Robot 也未恢复。旧认证资料不可假冒提交或跳过；如按开发计划统一重装，将使用新的可丢 Demo 数据、真实 Common E1/READY 重新登记，再跑交易。
4. T84 使用三个真实 ZK，但所有 JVM 都在一台 Mac 的 Colima，**不能描述为独立物理机器级 HA**。保持正式 Demo NO-GO。

**最终：隔离四 JVM 启动配置 P1 子项 PASS；严格 Common 全自动及业务 E2E NO-GO。**
