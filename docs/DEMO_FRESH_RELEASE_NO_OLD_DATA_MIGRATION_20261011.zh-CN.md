# Demo 清空重部署优先：不迁移旧业务数据（2026-10-11）

## 正确区分两件事

当前 OpenTradingCore Demo 的订单、资金、持仓和租户测试数据可丢弃。每次软件机制变更，优先使用一套确定版本的镜像，从全新数据目录部署，并从头验证；不为旧版本数据迁移或回放浪费时间。

运行中新系统的 HA 故障恢复是另一回事：节点故障后必须通过可信的最新完整快照和连续提交日志，恢复当前这次运行中的业务状态。Order、Trade 的恢复组件只是为了验证产品的 HA，而不是为了保留上次部署的数据。MD 从 Order 全市场快照恢复，不能引入无意义 MD-to-MD 重复日志。

## 本轮核对的事实

- Mac 项目 dc-saas 有 24 个容器。mac-saas-reset.py 只读 plan 成功，只涉及这一个项目和指定专属运行目录。单独保存的 P246 故障证据不属于可删除数据。
- Mac 安装脚本的 --check --full-cluster 只读预检查通过，但提醒现网 dc-saas 容器存在，必须核对镜像和配置。
- 本轮 Mac 开发镜像重新编译通过：Common SHA-256 298c0ad5d150747cfda122aac16f1faf3444f9621419fd7f21c88a5c03814af9，Order、Trade、MD 共用完全一致的 Common JAR。构建根目录：~/.opentradingcore/local-ha-clean-validation-20261011。构建时源码有尚未提交的变更，正式发布前需要基于最新 commit 重构建。
- 最新全量测试：Common 163/163、Order 337（0 失败，1 跳过）、Trade 249/249、MD 125/125。
- 已提交 Common ffd928c、Order 30ea736、Trade d4a9aa8。Order/Trade 提交位于独立验证分支，还没有合并正式 saas-crypto。
- 正式版本锁 release/saas-crypto-images.env 仍指向旧版 Order sha-7842df4、Trade sha-e5cebdd2aa191e98a3128886634cd3b5eca6d3e6、MD sha-48544e5。Mac 安装程序会强制应用这个锁。现在直接清空再执行原一键安装，只会装回旧版，不符合从新程序开始验证的目标。
- **目前没有冷重置，也没有替换线上镜像。** 不通过其他发布脚本或替代路径规避现有发布安全检查。

## 后续唯一发布路径

1. 精确锁定 Common、com.app.dc、Order、Trade、MD 五个提交，编译并跑全量自动测试。
2. 使用受支持的正式流程发布对应的最新不可变镜像，确保 arm64 可在 Mac 上启动，同时核对镜像内容和源码。更新正式发布锁后再执行校验；不能让锁继续指向旧程序。
3. 隔离旧数据目录，停止 dc-saas 项目，使用全新的 DEPLOY_ROOT 执行一键全量部署。无需迁移旧数据。
4. 新建 10 租户，验证注册/审批、Robot 默认启动、盘口报价、K 线、登录、API Key、真实下单/撤单/成交、资金/持仓/订单历史、Projection 和移动端。
5. 连续运行和记录 TPS、资源/磁盘增长、HA watermark、日志回收，再对 Order/Trade/MD 做符合门禁的故障注入。MD 必须先证明 Order 全市场完整镜像、旧 publisher fencing 和 Robot 对账。
6. 发现问题保存最小复现证据，修复后重新编译、再次清空 Demo、再次部署，不迁移老数据。测试通过前不宣称 HA 上线。

用户要求的两天归档保留用于稳定运行中的 Demo，不允许按日期删除仍被快照恢复、同步 Replica 或 Projection 需要的业务 CQ 日志。清空整个 Demo 和稳定运行中的 HA 日志回收是不同操作。
