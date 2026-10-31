# T370｜真实 Demo 交易恢复与 Order A 故障注入：成交 PASS / HA NO-GO（2026-10-31）

## 边界和规则

- Common 唯一负责 WAL、Snapshot、持久化复制、Epoch 授权、主备故障切换与恢复。Order/Trade 只存储、恢复、应用各自业务状态，不新增或复制选主逻辑。Gateway 透传，按 ZooKeeper 中 Common 已认证的业务物理 endpoint 和分区 owner 转发。
- Demo 数据可重建，但已有真实委托/成交的签名证据、WAL、Snapshot 与原始证书，在分析故障之前不得人为清理、篡改或将错误的 Epoch 重新标为 READY。不能为了“亮绿”而绕过拒写门禁。
- 本轮只使用 Mac 本地编译/镜像，不触发 GitHub Actions。

## 已通过的业务验收

1. 新租户 **C8SMUE** 自动审核、开户、Maker/Tape 两个独立用户入金、自动 Robot 初始化，Bootstrap 状态 **COMPLETE / DONE**。
2. Order/Trade A/B 四个服务在故障测试前均已真实启动并注册到 ZooKeeper。Gateway 对四个物理 endpoint 实际建立连接。Order B 启动时在 Trade A/B 就绪后 **TradeSvr partition primaries preconnected: 2/2**。
3. 统一部署配置：四个业务物理服务的 Order/Trade 入口分区路由都指向 `/dc/cluster/ordersvr-t364/partitions` 和 `/dc/cluster/tradesvr-t364/partitions`。P000 由 A 主、P168 由 B 主；ZooKeeper 路由 256 分区。
4. Robot 一度持续 **RUNNING / 40**；真实 Maker、Tape 成交回报为 `OrdStatus=Filled / ExecType=Trade`。APS→MD→Trade 标记价格恢复后不再持续返回 `MARKPX_NOTEXIST`。
5. 新 Projection 提交 **`82942f7`**（`.work/projectionsvr` 的 `saas-crypto`）：Order 原子撮合配对 `STATE_ATOMIC_MATCH_V1` 只有在后续 `STATE_MATCH_SETTLED_V1` 签名结算完成事件提交后才能生成两侧确定性 ExecID，保持 Common WAL 不变。JDK8 编译及 JUnit **7/7 PASS**。部署镜像 `local/otc-t369-projectionsvr:certified-settlement-history`，进程 `otc-t369-projection-host`；旧 `dc-saas-projectionsvr` 容器保留为停止状态。
6. 对首次 211 笔已认证结算做了 Trade 原始业务投影交叉校验：**422/422** 执行 ID、Order ID、数量、价格、Trade 成功结果一致，然后从真实认证账本补齐 `dc_orders_execorders` 查询表。T369 后续自动投影也经过实盘验证：213 笔→426 条，最终故障注入前 **219 笔签名结算、438 条执行历史**。从 Trade 成功结果回填历史费用；T369 新自动写入的费率/盈亏字段未直接从 Order after-image 推断，尚需从 Trade 财务投影完善映射。

## 18:42 Order A 故障注入：失败证据

- 注入前 Order P000 = Epoch 2、主 **OrderSvrA**、备 B、READY；P168 = Epoch 2、主 **OrderSvrB**、备 A、READY。
- `docker stop otc-t368-order-a-host` 后，P000 的 ZooKeeper 路由**没有自动转为 B**；P168 仍显示旧 READY。B 真实日志出现 **`Common poisoned primary Epoch cannot renew`**，业务入口报 `ORDER_COMMON_CERTIFIED_BUSINESS_STARTUP_DENIED`。非当前租户主节点 A 的故障仍波及 B，违背独立工作的可用性目标。
- 随后受认证重启 A 已可启动与注册；B 在尝试正常重启时失败，根因是 **`java.io.IOException: Common physically fsynced WAL head mismatch`**，Spring 启动失败，容器 `otc-t368-order-b-host` **Exited (1)**。不能把该拒绝改成无条件通过。
- 处置：不改 ZooKeeper owner、不覆盖认证水位、不清理或移动 WAL/Snapshot，不启动旧版 Order；停止 Robot 防止持续下单（`dc-saas-robotsvr` Exited(143)）。Order A、Trade A/B、Gateway、MD 与 T369 Projection 保留运行，**不代表交易可用**。
- 故障后原始业务投影/历史查询仍有 219 条 `STATE_MATCH_SETTLED_V1`、438 条 `dc_orders_execorders`，已完成的租户申请仍为 COMPLETE/DONE。拒写属于 HA 失败，**整体真实交易 GO 被撤销**。

## 下一步必须完成的修复（Common 优先）

1. **封存只读证据**：两 Order 物理节点本地 WAL、已 fsync HEAD、CommitIndex/Custody/Manifest/签名水位与 Snapshot；核对 P000 和 P168 的真实最后认证写入位置，定位重启 B 为什么比较到不一致 HEAD。不能靠删除不匹配尾部或伪造证明恢复。
2. 在 **Demo+Common** 先复现 A/B 故障：A 停止只影响 A 原 128 主分区；B 自己原有 128 主分区必须继续接受已认证写入。A 的分区需经过真实租约撤权、重新授权和可信 WAL 追平后由 B 接管。A 恢复后逐分区回归 Home，实测全 128 分区总耗时和 P99；反向 B→A 再测。任何中间态不可伪报 READY。
3. 验证同一物理 WAL 经真实交易写入、进程正常重启后可重新认证 HEAD；修复代码只能在 Common，保持 Order/Trade 与 Demo 适配器行为一致，禁止过度设计或在 Gateway 里补业务一致性。
4. Common 真实故障注入和重启 PASS 后，重新部署使用同版 Common 的 Order/Trade，再走新租户→自动审批→Maker/Tape 独立入金→双边报价→真实成交→Projection 财务与委托/成交核对。
5. 最终门禁：**Order/Trade A/B 双向自动主切、逐分区追平与回 Home、无重复成交/丢单/双主、Robot 继续交易、持久化历史与余额持仓一致**。当前 **HA NO-GO，交易未恢复正常**。

## 证据保留位置

- `/Users/kong/.opentradingcore/t365-ready-20261031-r1/data`（现有 Order/Trade Common 持久数据绑定；只读核对）
- `/Users/kong/.opentradingcore/t364-fresh-20261031-r1/born`（初始签名出生证据）
- `/Users/kong/.opentradingcore/t367-business-20261031-r1/control`（四业务节点公共配置）
- Docker 原容器日志：`otc-t368-order-a-host`、`otc-t368-order-b-host`，以及 `dc-saas-robotsvr`。
- T369 新源码位于 `.work/projectionsvr` 分支 `saas-crypto`，提交 `82942f7`，镜像 `local/otc-t369-projectionsvr:certified-settlement-history`。
