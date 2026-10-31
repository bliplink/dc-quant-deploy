# T360｜A 恢复后 128 个 Home 分区回切耗时及部分回切验收（2026-10-31）

**阶段状态：Common 控制面和真实单分区旧主物理退休单测 PASS；真实两 JVM、三 ZooKeeper、256 分区全部回切与交易仍 NO-GO。**

## 架构、无双主与耗时定义

- 常态 A Home P000–P127，B Home P128–P255；A SIGKILL 后 B 临时承接全部 256，A 重启后必须先追平 Snapshot/WAL，再由 Common 将 A Home 逐分区归还，B 原 128 主分区不停机。
- 对每个分区先把已确认写入的水位排空，签名 ZooKeeper CAS 变为下一 Epoch 的不可路由 RECOVERING，B 关闭该分区物理 WAL/Index/Custody 后生成旧 RSA 退休证明，A 完成最后 WAL 追平及业务回放；双节点新 Epoch 物理 RSA 恢复回执全部一致后才允许 READY 与本地 writer 安装。
- 当前 Stage 原始 RSA 证明绑定整份 Manifest 精确相邻版本，因此严格串行：最多 1 个分区处于协作 RECOVERING。并发 4 个会使先前 Stage 的原始签名版本在另一个 CAS 后过期，不能用不可信的模拟并发吞吐代替正式架构。
- 真实全回切耗时：T0 = A 已追平，开始第一个 Home 交接；T1 = 最后第128个真实物理双签 READY、本地业务状态与 writer 已安装，且完整分区 Census 显示 A/B 各128 主。总耗时 T1-T0。另记录 A 重启到首次追平时间，以及每个目标分区 B 暂停到 A READY 的 P50、P95、P99、最大值。

## 当前 Mac 实测与局限

- Common 本地 commit 2e45510。T359/T360 用真实 Demo RSA 私钥签名并 fsync 128 次 Stage，完整 256 分区 Manifest 与 ZooKeeper **内存 Fixture** 做 128 次模拟 READY CAS；1 in-flight 串行后的控制面测试不同次观测为 530、534、560 毫秒（包括模拟 READY）。这不包含真实 ZooKeeper quorum、Snapshot/WAL、真实双节点的恢复回执/认证 Ready，**不是 A 128 分区真正全回切耗时**。
- 中途中断 Fixture：A 原 Home READY 37，单个 RECOVERING 1，B 继续代持 A Home 90，异常 0。重建 coordinator 后能用原 RSA 持久 Stage 恢复 P037，尝试继续 P038 时遭到签名 Stage 单 in-flight 限制；模拟 P037 READY 后才继续。B 自己原始 P128–P255 128 主状态与 Epoch 不变。
- 真实 Netty + A/B Demo RSA 双分区测试：P090 双物理严格 ACK 后，读取当前 RSA 签名 Stage，旧主关闭真实 OS WAL、CommitIndex/Custody 并签原节点退休回执；同一 Netty 下 P128 仍可完成下一笔严格 ACK。此项没有为 P090 签发新 Epoch READY，因此没有假报无中断全回切成功。
- 由 CommonHomeReturnCensus 读取原始 immutable Home 布局和当前分区清单，展示 target、homeReady、peerReady、recovering、invalid、pending；只有全部128 READY 且无异常才 complete=true。未完成/缺证据不得报 GO。

## A 是否可能只切回部分主？

**可能，而且在逐分区切换时属于正常过渡。** 只要仍有 RECOVERING 或 B代持 Home，128/128 就没有恢复完成。损坏 WAL、旧主未签退休、A 业务回放未完成、双节点新 Epoch 恢复回执缺失时，当前分区必须停止在不路由的 RECOVERING；其他健康分区继续提供服务。Common 原有 Watch 对已持久化的签名 Stage 会尝试恢复，但尚无真实多 JVM 全量证据证明所有故障都能自动最终完成，故长期部分回切必须作为 NO-GO 告警，而不是超时后伪造 READY。

## 后续验收门槛

使用真实两 JVM + 三 ZK 对完整256分区循环执行 A SIGKILL/B接管/A追平/A逐一回Home/B SIGKILL/A接管/B追平/B归Home，逐分区核对旧 Epoch 退休、双签已提交水位/资金/订单/持仓、无双主、最后一次重启仍可取得严格 ACK。真实 T0/T1 收集后才能回答总回切秒数及暂停 P99。正式 Order/Trade Spring 尚未将完整旧主协作回执与新 Epoch READY publisher 接上，NO-GO 前不替换 T335/T336 容器，Robot 仍停止。原始 P193 A22667/B22668 未签尾保持只读。

**GitHub Actions 未使用；不增加 Order/Trade 专有 HA，不改 Gateway。**