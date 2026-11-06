# T528｜Common 升级连续性：实际数据身份、Gateway 与 Projection 代际检查（2026-11-06）

## 目标与结论

本轮停止在 Common 追加签名/选主/恢复协议，改为修复**升级流程错误**：升级本应保留 WAL、Snapshot、租户资金及业务状态；全新部署则必须把旧 Robot、旧账户与历史 Projection 水位彻底隔离。

**T528 实施：** 新增只读且失败即拒绝的 `tests/check_common_upgrade_continuity.py`，8 项 Python 测试全部 PASS；Mac T523 现场分别用 `upgrade` 和 `fresh` 模式实际执行，均返回预期的 exit=2 / NO-GO。没有改动或删除现存容器、WAL、Snapshot、MySQL 表、签名凭据；没有为了消除 1003 放宽 Trade 资金认证。

## 现场直接证据

| 检查 | 现状 | 验证结论 |
|---|---|---|
| Common 真正加载的 JAR | Order A/B 与 Trade A/B 的 Docker 实际 Mount.Source 都是 `~/.opentradingcore/t523-fresh-20261106-r1/common-t523-d2d1ce0-full.jar`，覆盖镜像里 `com.app.common-t520-common-only.jar` | SHA256 四份均 `b170df0dffd6d8cbeeb64ff3ac9865fe5a89aa803d49580bf0d78eae123801b2`；镜像名含 t520 **不等于**实际加载 T520 |
| 新 Order/Trade 数据 | `/srv/dc/data/t523-ready-v1/OrderSvr/{OrderSvrA,OrderSvrB}`、`TradeSvr/{TradeSvrA,TradeSvrB}` | 新卷，与此前 T398 代不相同 |
| 旧 Order/Trade 数据 | 原业务节点对应旧 `t398-ready-v1`、部分早期 T488 数据目录，物理挂载不等同 T523 | `upgrade` 检查四个节点均 `BUSINESS_WAL_SNAPSHOT_GENERATION_CHANGED` |
| Projection 的实际数据卷 | `otc-t454-projection-common-rejoin` 绑定独立的 `otc-t399-services-data` | 应与**之前的 Projection 卷**比较，而不是要求它与 Order/Trade WAL 共卷；本次 FRESH 仍复用同一个旧消费者卷 |
| Robot | `otc-t438-robotsvr-session-recovery` 在运行并按旧租户尝试下单 | `fresh` 仍有旧 Robot 写入者，拒绝混用 |
| Gateway | T527 已将 T523 A/B 四个节点接入 Gateway；四个容器均运行、`gatewayDiscovery.enabled=true` | **仅路由和节点运行 PASS**，不等于交易业务 PASS |
| 真实资金/Projection | T527 Trade A/B 没有非空 WAL，日志有 `TRADE_COMMON_SIGNED_FINANCIAL_RESERVE_MISSING`；Projection 历史 P250 水位 `2:258333` 超过新 Common 已签名水位 | 认证资金/真实成交/新 Projection **NO-GO** |

> **T527 文档中的版本表述纠正：** T527 将“镜像名称 `common-t520-business-smoke-r2`”误写成实际 Common T520，Docker 实际覆盖 JAR 源文件已逐个核对，应该以真实挂载 SHA `b170df...` 为准。T526 新 Common 虽在 Demo 通过测试，尚未替换 T523 使用的上述 T523 JAR，不得将它当成当前 Order/Trade 运行版本。

## 统一升级方式，明确分成两个模式

### UPGRADE｜保留旧数据的滚动升级

1. 记录旧 A/B 的真实 Volume + 完整 `nodeRuntime.dataRoot`、Snapshot、Common JAR SHA、分区来源和 Projection 消费水位；旧节点停机后仍可通过 **Docker inspect** 读取其 Mount。
2. 新 A/B 必须映射到经认证连续恢复的**同一份**物理 WAL/Snapshot 数据源（本次只读门禁只接受同一物理路径，不代替数据迁移证明）。如果要迁移物理路径，先走有可核验证据的迁移、再做人工校验；不可让脚本以同 Epoch 或容器 Up 自行放行。
3. 先验证四个新节点使用**同一份实际挂载 Common JAR SHA**，而不是看镜像 Tag；Gateway 的节点发布也必须打开。
4. 分区恢复和资金状态未完成前禁止切换真实业务入口、停止全部旧节点或宣布 READY；必须验证旧业务状态真实恢复、Order/Trade 完整业务 WAL、买卖双方冻结/解冻与提交。
5. Projection 可以使用**独立于 Order/Trade WAL 的数据卷**，但升级时不能无证明更换自己的消费者卷或水位；必须以同一 Common 数据身份消费。全程保留旧镜像和数据。

### FRESH｜全新开发环境

1. 建立独立 Common ZK namespace、签名成员、空 WAL/Snapshot 和独立业务数据代际；
2. **旧 Robot 停止服务/隔离，旧 Projection 的历史水位和 MySQL 业务投影隔离为旧数据集，**不允许它们继续向新服务发送订单或以旧 Seq 拉取新 WAL；
3. 通过正式自动审批创建新租户（请求必须带有效 `admin_password`，这是现有 Manager 的合法前置条件）、创建新交易员并通过新 Trade 的认证 cashIn 写入新 WAL；
4. 在新租户里重新自动启动 Robot，实测盘口报价/Tape/下单成交，核对两物理副本提交证据，最后核对新 Projection 与资金/持仓；
5. 未完成全链路前只能称为“新服务可启动”，不能称为交易恢复成功。

**运行要求：** 在操作终端预先从已有的 `.env.prod` 安全加载 `MYSQL_USERNAME`、`MYSQL_PASSWORD`（不在命令参数、日志或仓库中写出凭据）；两个模式均需 `--mysql-container` 执行只读水位查询。以下命令不会执行任何 SQL 写入。

### 命令：真实部署只读审计

```bash
python3 tests/check_common_upgrade_continuity.py \
  --mode upgrade \
  --approved-common-sha256 b170df0dffd6d8cbeeb64ff3ac9865fe5a89aa803d49580bf0d78eae123801b2 \
  --old-order-a otc-t488-order-a-ready \
  --old-order-b otc-t453-order-b-standby-parent-watch \
  --old-trade-a otc-t436-trade-a-margin \
  --old-trade-b otc-t452-trade-b-windowed \
  --new-order-a otc-t523-order-a-hostready \
  --new-order-b otc-t523-order-b-hostready \
  --new-trade-a otc-t523-trade-a-hostready \
  --new-trade-b otc-t523-trade-b-hostready \
  --projection otc-t454-projection-common-rejoin \
  --old-projection otc-t454-projection-common-rejoin \
  --mysql-container otc-t398-mysql
```

实际结果：四个 `BUSINESS_WAL_SNAPSHOT_GENERATION_CHANGED`，返回 `exit 2`，**UPGRADE NO-GO**。Projection 的旧消费者卷自身虽然未变，但无法安全消费已重新初始化的 Common 业务状态。

```bash
python3 tests/check_common_upgrade_continuity.py \
  --mode fresh \
  --approved-common-sha256 b170df0dffd6d8cbeeb64ff3ac9865fe5a89aa803d49580bf0d78eae123801b2 \
  --new-order-a otc-t523-order-a-hostready \
  --new-order-b otc-t523-order-b-hostready \
  --new-trade-a otc-t523-trade-a-hostready \
  --new-trade-b otc-t523-trade-b-hostready \
  --projection otc-t454-projection-common-rejoin \
  --old-projection otc-t454-projection-common-rejoin \
  --robot otc-t438-robotsvr-session-recovery \
  --mysql-container otc-t398-mysql
```

实际结果：`FRESH_DEPLOYMENT_STILL_HAS_OLD_ROBOT_WRITERS`、`FRESH_PROJECTION_REUSES_LEGACY_CONSUMER_VOLUME`、`FRESH_MYSQL_HAS_LEGACY_PROJECTION_WATERMARKS`，返回 `exit 2`，**FRESH NO-GO**。MySQL 真实只读检查：Order / Trade 消费水位表各有 **6** 条非零记录（最大 seq 分别为 **258333 / 101637**），历史订单投影事件 **550827** 条、资金/交易投影事件 **113006** 条。不得将这些表直接归零。

## 实现与测试边界

- 实际使用 `docker inspect` 的 **Mount.Source + Mount.Destination + 应用 Properties `nodeRuntime.dataRoot`**计算物理数据根。不会把 ZK Epoch 相等误认成数据相同。
- 实际通过挂载 JAR 文件字节 SHA256 检查跨 Order/Trade 四节点一致性，并强制要求与部署批准的 `--approved-common-sha256` **完全一致**（不会因四节点一起跑错版本而放行）。Projection 与其**原消费者卷**比较，不要求与 Order/Trade 数据卷相同。旧节点不强制运行，也不要求旧镜像有外置 JAR。
- 审计从当前环境变量 `MYSQL_USERNAME`、`MYSQL_PASSWORD` 只读查询 `dc_order_projection_watermark` / `dc_trade_projection_watermark` 行数；不输出密码或 MySQL 命令参数。FRESH 模式只允许**首次切流前**的空水位数据库（如已在新数据源产生合法新成交，必须通过数据身份签名另行验收）；不能继续消费旧 MySQL 历史坐标。
- 正常 `upgrade`、`fresh`、版本不一致、Gateway 未发布、旧停机节点、路径 traversal、未经批准的 Common SHA 和旧 MySQL 水位拒绝等共 **11/11 Python tests PASS**。
- 审计**只读取现有专用 MySQL 环境凭据（不显示、不持久化），从不读取用户登录密码/业务 RSA 私钥**，也不创建业务提交、ZK READY/签名/RSA；不执行 `docker stop`、重建镜像或 MySQL UPDATE/DELETE。
- 本工具只能做**结构性拒绝检查**：即便它 PASS，仍必须验证真实 Snapshot/WAL 签名、Projection **MySQL 消费水位和数据身份**及业务恢复/订单成交。仅新建消费者卷并不足以隔离旧 MySQL 水位。不能用脚本字段自称完成证据迁移。

## 下一阶段业务修复顺序

1. **先决定采用 FRESH**（本轮现网已换新数据卷，不应把它称为无损 UPGRADE），但必须将旧 Robot 与旧 Projection 隔离并给新业务表和水位另建真实来源；保留历史审计数据。
2. 管理系统使用正式带管理员密码的全新租户自动审批。T527 首次申请 `TB3EDF` 未提供自动审批必须的密码，状态 `PENDING` 是预期；后续正确申请请求遭执行环境安全检查阻止，**仍未真实完成自动审批**。
3. 新账户的 Trade `cashIn` 必须先真实写入 Common 双 RSA WAL、Balance，再运行新的 Robot；不能用旧账户直接下单或绕过金融 Reserve 校验。
4. 新 Projection 应以独立消费者卷和与真实已签名 CommitIndex 匹配的业务数据代际建立独立 watermark；不得通过强制回退历史水位覆盖原始资金/成交审计。
5. Demo Common 的 LOCAL 模式自动切换与生产 Order/Trade STRICT HA 是独立门禁；业务恢复成功也不能冒充自动 HA PASS。

**当前结论：** 检查规则已落地并通过真实 NO-GO 验证；`T523` 交易与自动 HA 尚未恢复。后续不能再以“容器运行”“Common 测试通过”作为项目结束证明。
