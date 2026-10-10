# 十租户持续运行与真实 MD 主节点故障注入验收（2026-10-10）

## 结论

**10 租户正常运行基线 PASS；MDSvrB 主节点故障期间业务连续性 FAIL；手动恢复后稳定性 PASS。** 系统**尚不能保证** MD 主节点失效期间十租户不受影响，更不能由此宣称 Order/Trade HA 已通过。

执行环境 Mac mini + Colima，`saas-crypto` 分支，10 个真实 TRIAL 租户，10 个 `trial-liquidity-BTCUSDT` Robot。未清理租户、未修改客户余额、未编辑 ZooKeeper 分区分配，未中断 OrderSvr / TradeSvr / MySQL / ZooKeeper 数据节点。

## 一、故障前只读核对与稳定性观察

逐租户核对：`A7C924`、`B7C924`、`BU1AN0`、`MZYMEX`、`NRZ5AE`、`R1GLNL`、`S0P0PZ`、`TLS5DL`、`U9DXN2`、`YGW9OH`。

- 全部十个：租户 `TRIAL`，流动性引导 `DONE/COMPLETE`，Robot `enabled=1`、`RUNNING`、`open_order_count=40`、错误码为空。
- 公开 `MDSvr/queryPublicMarket`：每个租户的 BTCUSDT 盘口至少十档买单、十档卖单且未交叉，均有公开最近成交；每轮跟踪最后成交 ID。对应独立 Tape 账户持久化 Trade postings 在观察期间全部增长。
- **故障前 601 秒，11/11 采样 PASS，错误采样 0**；10 个租户成交 ID 均持续变化；持续 400 挂单，磁盘约 87%。十租户盘口单轮慢请求大致 8–74ms。
- 独立 `check-tenant-ramp-readiness.py` 返回 `gate=BASELINE_READY_ONLY`、`nextRampAuthorized=false`、`reasons=[]`，表明仅达到基线，**不是**容量扩容授权或 HA 通过。
- MD ZooKeeper 的 256 个分区均为 READY：**MDSvrA Primary 128、MDSvrB Primary 128、MDSvrC Primary 0**。注意 ZK 的 READY 不证明可实际接管。

## 二、故障注入与影响

在仅这一次明确的主节点故障中，对容器 `dc-saas-mdsvr-b` 发送 `docker kill --signal=KILL`，模拟 **MDSvrB 进程突然退出**，监控全部十租户行情 API、Robot 健康、已挂订单和 Order 恢复信号。

**结果 FAIL：** 注入后立即只有 **6/10** 个租户的公开盘口还能正常查询；`R1GLNL`、`S0P0PZ`、`TLS5DL`、`U9DXN2` 受影响。随后 Robot 健康数下降至 **6/10**，四个受影响租户的 Robot 一度 `ERROR / RUNTIME_FAILURE`，挂单数降为 0。共 **18 个故障窗口采样，8 个存在业务故障**，因此不能以“容器恢复运行”代替业务连续性判断。

这次经 Docker 命令主动发起 SIGKILL 后，`unless-stopped` 配置**没有在本次操作中自动重启容器**，运维脚本需要**显式启动** `dc-saas-mdsvr-b`。这是人工调用 Docker 发出 kill 的观测结果，**不能外推为真实 OOM、进程自行崩溃时 Docker 一定不会重启**。故障注入脚本带恢复保护，不会在失败时遗留 MD B 关闭。

MDSvrB 恢复后重新初始化分区、安装十租户市场快照。注入后约 **52.3 秒**，十个租户公开盘口和 Robot 状态首次全部恢复正常；故障后仍查询到 ZK `P077`、`P141` 的 `primary=MDSvrB`、`replica=MDSvrA`、`epoch=1`，**没有观察到副本 CAS 晋升 / epoch 主节点切换**。不能宣称完成 MD 主从故障转移。

## 三、故障后的权威与持续性核对

- **再次连续 301 秒，11/11 只读采样 PASS，错误采样 0**：十个 Robot `RUNNING`，每个 40 笔挂单，总计 400；十租户最近成交继续增长；磁盘约 87%；盘口请求持续正常。
- OrderSvr A/B/C 与 TradeSvr A/B 均仍处于运行状态，未注入故障，也未切换镜像；最近两分钟三 Order 节点 `ORDER_PARTITION_RECOVERY_FAILED` / `PARTITION_NOT_READY` 检查均为 0。
- 对前八个自动化 E2E 租户的交易员 `trialtrader` 权威 MySQL `dc_orders_position` 验证：8/8 个用户长仓、短仓均为零；这些账户的活动订单查询结果为 **0**。此项证明示例交易员恢复后保持空仓，不是自动核对全部 Maker/Tape 交易记录的替代品。
- 主站和 Trade Web HTTPS 返回 200，MDSvrB 处于 `running`。已禁止进入新的 25 / 50 / 100 / 200 租户扩容阶段，等待 MD 故障 P0 修复。

## 四、修复门槛与下轮故障策略

对应 [MDSvr P0 Issue #5](https://github.com/bliplink/com.app.dc.mdsvr/issues/5)。

1. 开发真实**MD 主节点故障发现与接管机制**：ZooKeeper 带版本比较的 CAS epoch 晋升、已追平状态水位证明、旧主节点 publish fence、由 OrderSvr 权威快照安装后才允许新 Primary 发布；必要时明确 RTO，并提供双主 / 陈旧盘口判定。不能把 MDSvrC “存在”误作其已经是合法同步副本。
2. 对 Robot 的瞬时市场源丢失提供可重试、幂等、可对账的恢复路径，避免 `RUNTIME_FAILURE` 将盘口清空后无法恢复。历史挂单状态需与 OrderSvr 对齐，禁止简单伪造 RUNNING。
3. 先在隔离三节点环境完成带十租户连续流量的 MDSvr PRIMARY `SIGKILL` 回归、自动晋升、旧主节点归队、反向切换、交易流水及订单一致性。通过后再重做线上受控注入。
4. **OrderSvr** 仍采用 `SYNC_PER_RECORD`、所有指定副本 ACK；未具备端到端 write-drain、持久化复制确认和 Projection watermark 前，**禁止对 Order A/B/C 做直接 SIGKILL 故障注入或滚动升级**。TradeSvr 故障注入也需要独立检查状态及回滚安全门槛。
5. 本轮证明**正常十租户业务可持续运行**以及故障后可恢复，**没有证明单 MD 主节点故障下不中断**。后续验收必须比较：故障前、故障期间、故障后每租户行情有效性、成交推进、Robot 状态和资金/持仓一致性，而非只看 Docker 容器数。

## 五、证据

运行在 Mac mini 上的**本机只读证据文件**（不含账号密码/API Key）保存在：

`~/.opentradingcore/evidence/ten-tenant-soak-20261010/`

- `pre-fault-summary.json`：故障前 601 秒 / 11 次采样。
- `samples.jsonl`：读数时间序列与每租户盘口/成交 ID（仅本地保留）。
- `md-b-fault-result.json`：单次 MDSvrB 故障的 18 个采样点与恢复时间。
- `summary.json`：故障恢复后 301 秒 / 11 次采样。

本报告只汇总经过观察的业务状态，不声称所有复制副本 durable watermark 或跨 epoch 状态一致性已经完成。