# T279｜Common E3 LOCAL → E4 STRICT 安全预检（2026-10-29）

## 本轮真实结果（严格区分 PREPARED 与 READY）

**E4 STRICT 的物理双 WAL/双 RSA 预检 PASS；真实 E4 ZooKeeper CAS、E4 认证重启及未来业务严格 2/2 客户端 ACK 尚未验收，所以整体 P0 仍然 NO-GO，Order/Trade 不允许据此替换集群。**

1. Common 新增 `CommonCertifiedStrictEpochRearm` 只读准备入口。要求当前已认证 Manifest 的 E3 (或更高) `READY + LOCAL_DURABLE_ASYNC`、恰好两物理节点、同一个不可分叉 E3 WAL HEAD 的两份独立 RSA 回执。调用方还必须从两节点真实、已冻结的 WAL 获得**无额外尾部**证明，否则拒绝。只生成 **E4 STRICT RECOVERING（不可路由）**和预期 READY Manifest，不写 ZooKeeper、不颁发 Epoch/Primary 权限、不自动切换 ACK。历史 LOCAL 的客户确认永不追认为 Quorum。
2. 新增 Common 定向回归，验证：签名 E3 HEAD 一致才允许 E4 非 READY 预览；B 有更长尾部、错误 RSA 前缀、同一 Epoch 直接改 STRICT 均被拒绝；**未来独立 E4 WAL**只有 A/B 两份 RSA 实际 fsync 后才能推进 CommitIndex，单 A 签名不会成功；E3 身份不能使用 E4 签名 CommitIndex。此 E4 定向回归仅验证 WAL/CommitIndex 机制，不代表已对真实业务发出严格 ACK。
3. 另新增 `CommonRealE3ToE4StrictRearmPreflightTest`，读取此前及本轮真实 Docker SIGKILL 后的 A/B E3 原始 WAL，只在临时复制文件上利用既有 A/B RSA 分别签名，保护原始证据不被修改。**最新真实原始数据** `~/.opentradingcore/t124-live-kill-runs/20261029133129`：双方 E3 seq=3、同一 SHA256 `0935a4241ce2a5d1ab17137d29d2d8e5cec8c000e30346c69dbc0094a62ce689`，输出 `T279_REAL_A_B_E3_POST_REJOIN_RSA_SAME_WAL_HEAD_PREPARED_E4_NOT_READY=PASS`。这是物理 E3 数据一致性与*离线准备*证据，不能代替活节点冻结、CAS 与 E4 READY。
4. 使用 T279 新候选 Common Jar 再次运行**真实隔离 Docker+3 ZooKeeper+原 A/B/C RSA** 的两次 `SIGKILL`、E2/E3 Common 自动 READY、B 在线重新加入、E3 后续 TCP+RSA+fsync：**新运行退出码 0**。原始运行目录 `~/.opentradingcore/t124-live-kill-runs/20261029133129`；日志 `~/.opentradingcore/p0-20261029-evidence/t279-common-double-sigkill-bounded-watch-r2.log`。出现过一次退出码 58：脚本检查 E3 线程 READY 标记过早；容器随后确实打印合法 PASS，已把断言改为有边界的最多 10 秒轮询并重新运行，**仅 r2 退出 0 算最终通过**。这不是放松 READY 验证。
5. Common 完整本机 Maven（原始 A/B/C RSA 环境）`141 suites / 626 tests / 626 passed / 0 skipped / 0 failures / 0 errors`，退出码 0。既有 `ATSConfig.ini` 查找日志并未造成该次测试失败。

Common 本地候选分支 `codex/t177-common-saas-crypto-integration-20261027`，提交 `0f1f016`。本轮候选 Jar SHA256 为 `e999c30aadbab132d48095044880713e37d9ff9cfc00735e017210aa2ea41057`。未执行 GitHub Actions、未替换 Order/Trade 容器、未改动其他脏工作区文件或上传真实 RSA/WAL。

## 下一关：真实 E4 STRICT，不允许绕过

- Common 必须在两个活节点对旧 E3 写入设定安全冻结屏障，并真实确认 A/B 最终 WAL HEAD/业务快照/无分叉尾与相同 RSA 证明；先持久签名新的 Stage，再在真实 ZK **CAS E4 RECOVERING，必须不可路由**，不得让旧 E3 继续返回新业务成功。
- 让 A/B 通过同一个 Common 恢复入口分别安装 E4 baseline 与物理副本，验证旧 Epoch 撤权、两份签名及角色；之后才能通过认证 ZK CAS 发布 **E4 STRICT READY**，且不得直接删掉 `Common newer Epoch replica certified recovery required` 的恢复门禁。
- 在**新 Epoch 的新写入**上验证真实两份物理 fsync + CommitIndex + Custody 证书全链路后客户端 `QUORUM_DURABLE`；杀死其中一节点、重启、持续发送不同 opaque `byte[]`，验证无双主、无错误 ACK、状态一致。旧 E3 LOCAL ACK 一律不变。
- 真正全部 P0 通过后才能以相同 Common SHA/Bootstrap/Watch/恢复 API 替换 Order/Trade。集群层不得理解 GTC/IOC/FOK、订单/资金类型，业务层不得实现第二套 HA。

关联：`docs/T278_COMMON_AUTOMATIC_HIGH_EPOCH_REPLICA_REJOIN_20261029.zh-CN.md` 与 `docs/ARCHITECTURE_SIMPLE_COMMON_BOUNDARY_20261029.zh-CN.md`。
