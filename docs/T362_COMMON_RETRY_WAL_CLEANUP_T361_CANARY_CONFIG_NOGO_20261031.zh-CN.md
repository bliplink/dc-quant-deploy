# T362｜Common 恢复失败 WAL 句柄释放、T361 只读 Compose 结构检查与 Robot 阻塞（2026-10-31）

> 状态：**Common 候选 WAL 清理代码与 14/14 定向回归 PASS，T361 镜像 PASS；真实 Docker 替换、机器人报价和交易 HA NO-GO。** 本轮没有停止或替换旧 Order/Trade、未修改 P193 WAL、未使用 GitHub Actions。

## Common 本轮真实修改

- Common 本地源码 commit **a0599cb**：修复 `CommonCertifiedNodeRuntime.armAutomaticPhysicalRecoveryWatchExact` 在已经签名 READY 的后置阶段建立新 Epoch 物理分区、但 `businessReplay` 返回不完整或 `installCertifiedRecoveredPartition` 拒绝时，新建候选 WAL 未关闭、可能持有 OS 文件句柄并阻挡下轮恢复的问题。
- Watch 现使用唯一 Common 的 `installRecoveredCandidateOrClose`；任何未通过业务回放、旧 Epoch 隔离或物理 ZK Grant 的候选关闭其物理 WAL/Index/Custody 后才允许下一轮新候选重试。关闭过程失败保留原异常并附上 suppressed，不能静默放行客户 ACK；已成功安装的候选不能关闭。
- `CommonCertifiedNodeRuntimeTest` 加真实 Netty/RSA 单分区验证：T362 人为拒绝新的业务 replay → 候选 WAL 真正关闭 → 旧节点共享 Netty 端口未变且无新 Primary writer → 用新的候选在相同 Epoch 完成已有测试的业务状态安装。**定向 14 tests，0 failures/errors，Maven exit 0。**
- Common 完整 668 项 RSA/WAL/P193 回归正在运行，结果以最终 Maven 退出码补记。暂不把定向通过等价于完整 HA 自动互切。

## T361 Compose 的明确只读结果

已使用原 `compose.yaml` 加 T329–T336 叠加及 `compose.t361-fresh-common-home.yaml`，开启 `order-cluster`、`trade-cluster`，`docker compose config --no-interpolate --format json` 成功读取完整结构：

- `ordersvr`、`ordersvr-b` 正确选择 **local/otc-t361-ordersvr:common-home-canary**；`tradesvr`、`tradesvr-b` 正确选择 **local/otc-t361-tradesvr:common-home-canary**。
- 四服务的独立 `nodeRuntime.dataRoot` 分别是 `/srv/dc/data/t361-fresh/OrderSvr/OrderSvrA`、`OrderSvrB`、`/srv/dc/data/t361-fresh/TradeSvr/TradeSvrA`、`TradeSvrB`，不能混用旧 P193。
- MySQL `t361-fresh-mysql` 与 ClickHouse `t361-fresh-clickhouse`，而原 T318 Genesis、原 A/B RSA/public keys 全为只读挂载。
- **这只是 `--no-interpolate` 的 Compose 结构核对，不证明敏感环境变量完成真实展开，更没有执行 `docker compose up`。** 新建 `.env.t361.paths` 曾被执行环境明确拒绝（policy_rejected），此前尝试带展开变量的 shell 操作也曾安全检查拦截；不改旧证据、不强行用错误路径启动。

## P193 与 Robot 真实读证

- `T328_SIGNED_ORDER_WAL_ROOT=/Users/kong/.opentradingcore/dc-saas-runtime-clean-20261016/data/t330-fresh/OrderSvr python3 tests/verify-t328-signed-order-ab-wal-readonly.py` 最新实际执行，**255/256 分区 A/B 字节一致**，P193 A=22667、B=22668（B 多未认证 1 帧）。脚本严格返回 exit **2** `T328_ORDER_AB_RESTART_BLOCKED`、`noTruncation=true`、`noBusinessApply=true`。
- 当前线上仍 Order A/B T335、Trade A/B T336，Robot Exited(143)。Order 实时 `ORDER_PERF_STATS` 仍 0 新委托与成交。
- APS 容器近期真实日志可见 BTC、ETH、SOL、UNI 每秒 `markPriceUpdate`，但近期 grep 没有得到 `bookTicker/depthUpdate` 的新鲜报价证据，不能以标记价替代 Maker 挂单有效 BBO，也不能虚称 Robot RUNNING。

## 唯一发布门禁

先让 T361 Compose 正式变量与原 T318 有效签名路径在受支持的执行环境下通过验证，再启动完全隔离的新数据服务并确认四个 Common Node READY、真实 ZooKeeper 注册、每分区 WAL/Replica 持久 ACK。下一步按“新租户实际自动审批 → Robot 两个交易员正常开户/入金 → Maker 持续盘口 → Tape 真实点价/成交 → Order/Trade A/B 自动 SIGKILL→追平→Home 128/128 回切、真实计时及账本一致”一次验收。业务运行时自动 Watch 和签名恢复接线仍需补完；没有全部实测不能宣布恢复成功。
