# T363/T364｜真实新 256 分区 Common E1 Genesis 双 RSA 出生 / E2 业务恢复 NO-GO（2026-10-31）

> 真实验收：**ZooKeeper 新命名空间原始 E1 清单、Order/Trade 各 256 分区 A/B 物理出生签名、独立双 RSA Genesis Quorum PASS**。**业务零状态安装、首次 E2 READY、正式 Order/Trade 镜像替换、Robot 报价和真实成交均未通过。** 未更改原 T330 P193 WAL，不使用 GitHub Actions。

## 发现原 T361 配置不能当成全新签名集群

- T361/T362 继承了历史 T318/T319 Spring 原始属性，Manifest 仍指向 `/otc/t318-virgin-20261029-r1/order|trade/manifest`，当前 T330 已在该真实 E2 命名空间产生并保留交易数据（Order P193 B 多 1 条未认证 WAL）。单独使用 `t361-fresh` 空业务数据目录不等于重新签署旧 Epoch 的 committed HEAD。
- 新增只读 `tests/verify-t363-fresh-cluster-lineage-readonly.py` 与 `tests/test_t363_fresh_cluster_lineage.py`，实际核对完整 Docker Compose 叠加并返回 **exit 2 / `FRESH_WAL_REUSES_PRIOR_ZK_EPOCH_WITHOUT_CERTIFIED_CHECKPOINT`**；5 项配置 fail-closed 单测通过。不会把有效旧 E1 出生签名伪装成新的 E2 持久提交权限。

## T364 实际新 ZooKeeper 与原始双节点签名

- 全新真实三 ZooKeeper 上命名空间：`/otc/t364-fresh-20261031-r1/order/` 和 `.../trade/`。原始 Manifest 使用正式 `NPC1|1`，256 分区 RF2 STRICT、Epoch 1 **全 RECOVERING / READY 0**。第一次数据写入后从真实 ZK **get -s** 读取，每服务 version 0、generation 1，和本机原文件逐字节一致。
- 固定 Home：P000–P127 **A Primary / B Replica**，P128–P255 **B Primary / A Replica**。原 T318 奇偶交错 Home 不是新目标。Common 新增 `CommonOriginalE1FleetFirstActivationStageTest.fresh128HomePlanPreservesOriginalBuddyThroughSignedE1ToE2`；该测试套件 **5/5 PASS**。
- 使用本地最新 T362 Order/Trade 镜像，`otc-t84-source-integrated-net` 和原独立两组 RSA-2048 钉住公钥，在每个真实 JVM 原始 ZooKeeper 同租约 session 下依次运行 E1 原始出生程序。Order A、Order B、Trade A、Trade B **各256/256 `COMMON_FIRST_BOOT_ONLY_LOCAL_RSA_E1_VOTER_FLEET_FSYNC_PASS`**，四进程均 exit 0；各节点独立在 `~/.opentradingcore/t364-fresh-20261031-r1/born/<service>/<node>` 写入本人 RSA 出生凭据、业务初始镜像和原始零 ACK WAL 认证根。没有重新复制 T318 旧签名。
- Common 新增显式 opt-in 真实证明器 `T364OriginalE1DualPhysicalGenesisSealTest`；先**全量检查 256 个分区两物理节点原始镜像字节一致、RSA 私钥身份签名合法、ZK 新命名空间原始零 ACK WAL 凭据**，然后用正式 `CommonCertifiedGenesisQuorum.sealAndVerify` 原子 fsync 发布。Maven exit 0；Order **256/256 Genesis Quorum / 512 物理 A/B 原签名回执**、Trade 同样，合计 **512 双签 Quorum / 1024 原始回执**。这还不是 E2 READY。
- 新原始证据和全部本地私有配置均位于 `~/.opentradingcore/t364-fresh-20261031-r1/`；Common test 不接受其他 Born root 或旧目录，不生成用户密钥，私有原始应用配置不入 Git 仓库。

## 正式业务零状态安装：已找到实际失败点，安全保留原数据

1. 首次 Order A/B 安装被 Common 拒绝 `COMMON_FRESH_PHYSICAL_ORIGINAL_ROOT_NOT_MOUNTED`，缺少新的各分区 `durableTransactionRoot` 物理目录；随后在独立 T364 data 下分别创建四节点各 **256 个空目录**。
2. 第二次安装被 Common 拒绝 `persisted original Genesis bytes/census differ`：T318 私有模板仍按奇偶主备，和新签署的 T364 **128/128 Home** 不一致。随后使用 `tests/align-t364-signed-e1-home-config.py` 只修正**尚未签署的**新私有恢复配置（每分区 primary/replica、两侧 RSA pin/host/原 WAL 路径），不改 Genesis/公钥/签名证据。全部 4 套安装属性和 A 的 first-ready 属性均确认 128/128。
3. 后续批量启动四个恢复进程被执行平台**安全检查阻止**；部分已经发出的 Docker 子命令启动后，Common 明确报 `COMMON_FRESH_E1_ORIGINAL_VOTER_NOT_LEASED`。代码 `CommonZkOriginalE1Census.requireCurrentFencedZeroHead` 要求**两个真正的原始物理 JVM 同时持有独立 session 的 ZK ephemeral lease**，不是两个进程各自短时依次持租约。故没有认证 E1 committed-head，更不允许 E2 READY。
4. 失败后只读检查发现 T364 **Order B 4 个分区 P000–P003** 事务根已写 `journal/ledger/sealed`，其余未安装；不能当作尚未使用的新 Root 直接重试或覆盖。若签名恢复 Ledger 无法独立认证续跑，需**重新创建 T365 独立全新命名空间与出生签名**，而非清除、重签 T364 原 Genesis。
5. 再次从真实 ZK get -s 复核两个服务 Manifest 仍是 **version 0 / generation 1 / 256 RECOVERING / READY 0**，本地 Quorum 各 256/256 原证明存在；旧 Demo T335/T336 正式容器未替换，Robot `Exited (143)`，Order 历史 P193 尾部留存。

## 经过代码核对的下次安全 E1→E2 编排边界

- 通过 Common recovery-only 的已有 B/A **hold** 路径保证两个独立持久 ZK 租约；安装 A 的真正 E1 业务零状态时 B 必须稳定 hold，直到 A 完成 256/256 `DurableRecoveryInstallLedger.REPLAY_COMPLETE`；之后 A 持续活着，B 才从 hold 切换到安装并达到同样 256/256。不能两个一次性短命安装进程竞争/缺席租约；必须先验证物理租约的 session owner，再开始改业务 WAL。
- 首次 E2 READY 由 A 的 **CommonOriginalE1FirstReadyActivation** 在真实 A/B 两节点原始租约均独立且两个物理零状态均持久安装后，使用新 RSA 签票并以 ZK 原始 version 0 CAS 到 E2 STRICT READY。未达到门禁前绝不运行 Order/Trade 正式业务。
- E2 发布之后再将 T362 Order/Trade 业务服务加入新的 ZK namespace 与独立数据库，复验正式 Gateway 注册→全新租户自动审批→两个 Robot 交易员入金→盘口持续报价→Tape 真实成交→Order/Trade 双向故障和 128/128 Home 回切总耗时。Business READY 和真实 HA 仍要单独验收，不能用控制面 READY 代替。

**当前最终状态：T364 已拥有真实双签 Genesis，但 E2 没有发布、交易没有恢复。平台拦截的恢复容器批量启动不应通过拆分命令等方式绕过。**
