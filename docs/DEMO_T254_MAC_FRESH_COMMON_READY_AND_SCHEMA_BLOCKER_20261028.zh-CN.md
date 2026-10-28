# T254｜Mac Demo 全量 Fresh Genesis 与业务 READY 复核（2026-10-28）

## 结果范围
此报告对应真实 macOS/Colima dc-saas Demo，使用离线本地容器、无需 GitHub Actions。用户明确允许全部旧 Demo 业务数据无备份删除。实际已移除原 24 个容器并清空旧 data 及 ZK/ClickHouse 持久化目录；未更改独立 otc-common-ha-demo 项目。

### Common／Order／Trade 已核验 PASS
- Common 原始 E1：OrderSvrA/B、TradeSvrA/B 每节点 256/256 RSA 初生签名和原始零提交证据，Order/Trade 两个服务各自完成原始双签封存（两个各 256/256）。
- 真实 ZooKeeper 授权：Order 与 Trade manifest 都由 `NPC1|1` 经严格 A/B 原始证据 CAS 到 `NPC1|2`，P000/P001 显示 E2 READY/STRICT_QUORUM。
- Order 的第一次签名票据 fsync 后，B 真实 lease 消失导致 E1→E2 CAS 未完成；T253 Common 修复为验证既有票据每字节内容、真实原始 RSA 签名及未更改 E1 证据后继续 CAS，不重新签发、不跳过租约或签名。真实 Demo 返回 `COMMON_ORIGINAL_FIRST_E2_READY_CAS_PASS`。JUnit 5/5 PASS。
- T254 纠正了 CommonCertifiedPartitionRuntime 的二进制 open(...) 签名缺失（包含 CommonOriginalFirstReadyBusinessGate 参数）造成的 NoSuchMethodError。Order/Trade 镜像的完整 Common Jar SHA-256 均为 `a201547655a8becbbc848d37ad2df6d78dbc19db5416d6061f27e9cc8bf16851`。
- Mac 安装器曾预先生成 512 条 E1 Gateway 兼容路由，与真实 E2 manifest 不一致。逐条验证旧派生数据来源后，仅清除 /dc/cluster/{ordersvr,tradesvr}/partitions 下的 512 条 E1 记录；没有改动 Common 认证 manifest 或 WAL。Common 自己恢复发布各服务 256/256 E2 派生路由。
- 最终四个业务 JVM 日志分别返回 `Started OrderSvr` / `Started TradeSvr` 和 `COMMON_GATEWAY_DISCOVERY_CERTIFIED`，33036/33041/33037/33046 与 Common TCP 真实监听存在，容器四节点均为 Up（观察时重启次数为 0）。

### 仍 NO-GO：真实新租户、Robot 与成交
- 全新 MySQL 初始 `dc_tenant` 为 0 条。
- `python3 tests/verify-tenant-auto-approval.py` 通过正式 Gateway 创建申请后，申请 `3d89c8075a1a491abc2ba1e8e375852e` 仍为 `PENDING`，没有自动批准。
- ManagerSvr 具体 SQL 错误：`Unknown column 'location' in 'where clause'`（新的 `dc_symbol.location` 缺失）。
- RobotRuntimeService 具体 SQL 错误：`Unknown column 't.liquidity_source' in 'where clause'`。缺失 `dc_tenant.liquidity_source` / `source_switch_state`，且 `dc_tenant_data_source` 等产品数据源结构也不完整。
- 根因是 Mac 安装包的 2026-10-20 快照使用 27 份旧 SQL 迁移，而现有 Manager/Robot/产品代码要求更新的结构。不是再次发生 Common 认证损坏。

### 已修改并验证的源码
- Common 源码工作区本地提交 `c76a6e9`，对应 `tests/patches/t253-common-e1-ticket-resume.patch`。
- Mac 安装包工作区本地提交 `9405b24`，对应 `tests/patches/t254-mac-fresh-schema-parity.patch`。补齐 9 份迁移、显式迁移顺序及重复部署安全 DDL，新增业务数据库 Schema 运行时校验。
- Mac 数据库迁移离线/静态测试 5/5 PASS，安装脚本 `bash -n` PASS；Common 最终 T254 Jar 签名票据测试 5/5 PASS。
- **执行阻断：** 真实 MySQL 上执行补缺迁移的请求被执行环境安全检查拦截，未对现场数据库执行这些 DDL。没有尝试换途径绕过阻断。

## 真实验收状态
| 关口 | 结果 |
| --- | --- |
| Mac 清空旧数据、重建基础设施 | PASS |
| Order A/B 和 Trade A/B 真实双 RSA E1 Genesis | PASS |
| Order/Trade E1→E2 ZooKeeper CAS | PASS |
| Order/Trade 四节点 E2 业务启动和 Gateway 发布 | PASS |
| Mac 缺失迁移的源码与静态验证 | PASS |
| 当前 Demo 数据库补迁移 | 未执行：操作被安全检查阻断 |
| 新租户自动审批 | FAIL（新申请仍 PENDING） |
| Robot 持续报价、Tape 真实成交 | 尚未通过 |
| Order/Trade A/B SIGKILL 自动互切、交易一致性 | 尚未通过 |

## 未完成的必要验收链
通过受支持的标准部署/数据库迁移渠道**执行并验证**这 9 份缺失 SQL；之后使用正式 Gateway 再次申请一个全新租户，核实自动 APPROVED 和 trial Robot Bootstrap；再验收盘口报价、两交易员真成交、Tape 成交、账户余额与持仓；最后在实际业务持续运行时进行 A/B 主节点故障注入和恢复前后 WAL/资金/委托/成交一致性检查。切勿把仅 JVM Up 或原始 Genesis PASS 当作完整交易 HA PASS。