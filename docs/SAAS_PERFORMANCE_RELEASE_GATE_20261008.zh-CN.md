# 2026-10-08 22:13–22:25 OpenTradingCore SaaS 性能版生产发布门禁

**结论：NO-GO。** 本文是实时核查记录，不是可重启授权。生产实际镜像未改变，生产 release-lock `release/saas-crypto-images.env` 未被覆盖。

## 已发布的独立 GHCR 优化镜像

候选完整镜像锁放在 **`release/candidates/saas-crypto-performance-20261008.env`**（禁止生产自动 source），仅变更以下三个服务的 immutable SHA，其余服务沿用目前 release-lock：

| 组件 | 旧生产镜像 tag | 候选新 tag | 构建证据 | 多架构 manifest digest |
|---|---|---|---|---|
| Order A/B/C | `sha-26b01eb` | `sha-52e5ca3` | [Order Actions 37779342821](https://github.com/bliplink/com.app.dc.ordersvr/actions/runs/37779342821) success | `sha256:b0f6c5f09a32d815564b3e8030a6b3c86124d27fd260a23b65c4c08a1ffc1782` |
| Projection | `sha-2d54c9d3234b948a8ed0a61e9b05c22b499d6f5a` | `sha-623bd68` | [Projection Actions 37789104203](https://github.com/bliplink/com-app-dc-projectionsvr/actions/runs/37789104203) success | `sha256:3dce230a0c39139fef45e32a5b563684edc63db1452802b5f62aa0fe7bfa88aa` |
| Robot | `sha-abd7efa1ffa7921f8c384f92c09f25c46419f63b` | `sha-dfef5152400a83bc2bb77a4e3de64a7d0d0e8536` | [Robot Actions 37781218043](https://github.com/bliplink/com.app.dc.robotsvr/actions/runs/37781218043) success | `sha256:8d17e33522b20ec47c895d0f7ae3c596e2d21f389676a0daea099e3c5695044f` |

Projection 的 `projection.order.binary.watermarkBatchOptimized` 仍**默认 false**；它不是本次无条件启用的参数。Order 15s ZooKeeper 客户端会话配置也仍未在生产进程生效。仅发布新镜像不代表该参数已生效。

## 现场生产证据（只读）

- 22:13 Mac mini：Colima 8CPU/16GiB、VM CPU PSI some avg60 **77.50%**、MemAvailable **472816 KiB**、SwapFree **32 KiB**，Host 数据盘余 **40GiB**；50/50 Robot RUNNING、活动报价记录数 2000。Order A/B/C、Trade A/B、Robot、Projection、ZooKeeper、MySQL 没有重启/OOM。任何「50/50 表面正常」都不代表 HA 通过。
- `tests/order_ha_rollout_gate.py --target OrderSvrA` 当前 **NO-GO**：CPU PSI 78.53% > 30%、MemAvailable 469480 KiB < 2097152 KiB、SwapFree 84 KiB < 262144 KiB。由于资源门禁未过，未继续做重负载 ZooKeeper topology 轮询。
- 核心持久化数据此前已读到约 **88.82 GiB**；Mac 当前内部空闲 40GiB，独立备份介质未发现。不能只在同一磁盘复制数据并称为独立备份，也不能直接 `colima stop/start` 或重建 Order/Trade Journal。
- 生产 MySQL 读取 **125 个 Order** 和 **123 个 Trade** 水位分区，使用每分区索引 event tail 的只读查询对比，发现 **4 个数据库内部不一致分区**：

| 流 | 分区 | MySQL watermark (epoch/seq) | MySQL 已保存事件尾部 (epoch/seq) | 差额 |
|---|---|---|---|---:|
| Order | P054 | 85/109061 | 85/109062 | 1 |
| Order | P138 | 85/9146 | 85/9151 | 5 |
| Trade | P123 | 1/3915 | 1/3917 | 2 |
| Trade | P186 | 1/9485 | 1/9487 | 2 |

Trade P232 的库内 watermark 与尾部同为 1/7025，但最后更新于 **2026-10-08 09:18**，仍需与 Trade committed journal high watermark 核对。数据库的尾部与水位一致也不能证明与权威源 journal 一致。
- `P054` 最新事件 `P054:85:109062` 在 12:48:34 写入 `dc_order_projection_event`，水位仍停在 `P054:85:109061`；这需要权威 committed journal / Order-Snapshot / event payload 与业务表逐项审计，**禁止直接 SQL UPDATE watermark、DELETE event、人工填补 seq**，否则可能掩盖未提交资金/成交/历史。

## 新增 fail-closed 门禁

`tests/projection_watermark_tail_gate.py` 是只读校验：两个流逐水位分区使用事件 `(partition_id,source_epoch,journal_seq)` 索引的最后一条已持久化事件做比较，发现差异输出 `PROJECTION_WATERMARK_TAIL_NO_GO` exit code 2，不改变数据。配套 `tests/test_projection_watermark_tail_gate.py` 有已知四缺口、逆序水位、跨 epoch、缺证据、重复分区等测试并接入 GitHub Actions。`PROJECTION_DB_TAIL_MATCH` 也**不授权发布**；还要继续对权威 Order/Trade committed journal、replica、业务表、交易状态的全链路核验。

## 安全上线顺序（必须按序满足）

1. 提供独立备份介质（实际剩余空间至少覆盖 ~89GiB 核心数据及增长余量，建议 200GiB+ 独立存储），规划短维护窗口；对 MySQL 做一致性备份，对 Chronicle Order/Trade Journal/快照做 quiesce 或一致性复制验证，并实际演练恢复，禁止只备份正在写入的不一致文件集合。
2. 对照 Order/Trade 提交水位、Journal、Projection 已入库事件、业务订单/成交/资金持仓，定位 P054/P138/P123/P186 四处库内不一致，以及 P232 的外部源积压。解决每条事件是否已应用的问题，而不是单纯推进水位。
3. 增加 Docker VM 空闲（Order HA 门禁 CPU PSI avg60 <=30%，MemAvailable >=2GiB，SwapFree >=256MiB），恢复 ZooKeeper 连接稳定，暂停/削峰 Robot 并完成资源验证。没有独立备份与全局 quiesce 不允许冒险改 Colima 资源。
4. 维护窗口中逐节点按 Order 主/副本分区 topology、epoch、commit sync gate 滚动更换 Order A/B/C 和 15s ZK 参数；Order/Trade failover 注入必须证明已确认订单、执行、余额、持仓均一致，无双主、无重复成交、恢复副本追平。
5. 最后基于上述全链路水位合格条件受控升级 Projection（先 flag=false）、Robot；验收 50/50 报价、客户报价可吃单、真实 ACK p95/p99、MySQL 投影追平，再单独试验开启 Order Projection 批内水位 flag=true，比较 baseline 并保留回滚到旧 immutable SHA 的能力。
6. 50租户/连续长稳与 HA 注入通过后，才按 75→100→150→200 分批压测；每步包含真实订单 TPS、复制延迟、CPU/内存、Projection lag、Robot 实际报价数。

**截至记录生成时，生产实际未部署候选镜像，也未执行数据库/Journals 数据修复、清理或停机。上述步骤不能用无风险证据不足的“强行上线”替代。**
