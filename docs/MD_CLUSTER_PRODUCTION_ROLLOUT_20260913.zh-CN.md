# MDSvr A/B/C 生产滚动升级验收（2026-09-13）

## 结果

- MDSvrA、MDSvrB、MDSvrC 均运行镜像 `ghcr.io/bliplink/mdsvr:sha-5e8710f`。
- 三个镜像均内置 `io.github.bliplink:com.app.common:3.0.12`，JAR SHA-256 为 `e447480cb7ca01097e18afff7a470bdd72d770f6a823aba6b70d433a3a895438`。
- ZooKeeper `/dc/cluster/mdsvr/partitions` 共 256 个 assignment，全部为 `READY`；最终 primary 分布为 MDSvrA=128、MDSvrB=128、MDSvrC=0。
- MDSvrC 保持热副本/learner，可用于下一次排空、升级和扩容。
- 三个容器均 `running`、`RestartCount=0`、`OOMKilled=false`，滚动升级期间未同时重启两个 MD 节点。
- `WEB_E2E` 的 BTCUSDT、ETHUSDT、SOLUSDT、UNIUSDT 均通过逻辑 `MDSvr` 查询返回 `code=0`、10 档买盘、10 档卖盘和正数 MarkPrice；四个 Robot 均为 `RUNNING`，挂单数分别为 42、40、40、40。

## 实施顺序

1. 以旧镜像启动 MDSvrC，并将 C 作为 256 个分区的 learner 预热。
2. 先灰度迁移一个活动分区，再以 8 个分区一批将 A 的 127 个剩余 primary 排空到 C。
3. 升级已排空的 A，确认活动市场在 A 上恢复为 `REPLICA`。
4. 使用 `--target-ready-role REPLICA`，以 32 个分区一批将 B 的 128 个 primary 排空到 A，再升级 B。
5. 将 C 的 128 个 primary 排空到已升级的 B，再升级 C。
6. 全量验证 assignment、镜像标签、容器健康、活动市场和 Robot 状态。

生产证据保存在：

- `/data/dc-saas-runtime/evidence/md-a-to-c-roll-20260913`
- `/data/dc-saas-runtime/evidence/md-b-to-a-roll-20260913`
- `/data/dc-saas-runtime/evidence/md-c-to-b-roll-20260913`
- `/data/dc-saas-runtime/evidence/md-c-to-b-roll-resume-20260913`

## 耗时结论

本次慢点不在 MDSvr 历史数据恢复，而在每批调用 `zkCli.sh` 完成 assignment 全量读取、CAS 前置读取、写后回读，以及等待活动市场的新 epoch `MD_MARKET_READY`。8 个分区一批排空 127 个分区需要 16 批，实际约 25 分钟；同样的安全协议改为 32 个分区一批后，128 个分区只需 4 批，实际约 7 分钟。

首个活动分区仍应使用小批灰度。灰度验证通过后，可使用工具允许的最大批量 32；不要通过取消 CAS、READY 门禁或写后校验来换取速度。后续可进一步优化为复用 ZooKeeper 会话、批内强校验加周期性全量校验。

## 活动路由清单注意事项

`md-active-routes.jsonl` 必须来自当前运行状态，不能仅以 `enabled=1` 判断 Robot 活跃。此次 `ROBOT_E2E_20260909105413/depth10` 虽然仍 enabled，但数据库状态为 `ERROR`、挂单数为 0，导致 P056 的新 epoch READY 证据永远不会产生，滚动工具因此按设计超时并停在 `RECOVERING`。

处理方式是保留超时和原计划证据，核对数据库确认该路由失效，从活动清单移除，再通过原计划、实时 znode 值和 dataVersion 的精确比对完成该批。真实活动的 `WEB_E2E` 四品种仍逐条执行 PRIMARY READY 门禁。

活动 Robot 至少应同时满足：

- `enabled=1`
- `runtime_status=RUNNING`
- `open_order_count` 达到配置目标
- 心跳/更新时间新鲜
- 正数参考价格或当前市场 READY 证据

## 滚动工具

`tests/md_cluster_roll_drain_host.py` 支持 learner 和 replica 两种目标预热角色：

```bash
sudo python3 tests/md_cluster_roll_drain_host.py \
  --source MDSvrB --target MDSvrA \
  --active-routes /data/dc-saas-runtime/evidence/md-active-routes.jsonl \
  --target-container dc-saas-mdsvr \
  --target-ready-since 2026-09-13T13:28:57Z \
  --target-ready-role REPLICA \
  --evidence-dir /data/dc-saas-runtime/evidence/md-b-to-a-roll \
  --batch-size 32 --ready-timeout 90 \
  --confirm-root /dc/cluster/mdsvr/partitions
```

兼容参数 `--learner-since` 仍可使用，等价于 `--target-ready-since`；默认目标角色仍为 `LEARNER`。
