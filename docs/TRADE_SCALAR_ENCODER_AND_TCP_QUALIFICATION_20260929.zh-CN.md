# Trade 去重编码减分配、TCP 异常与提交吞吐前置验收

日期：2026-09-29。Trade 提交 `520dfc5`、最终运行时兼容提交 `5c21a5136cb080325dbba003f580913311e5088b`。本轮连续完成编码优化、兼容/屏障回归、真实复制 TCP 故障、异常 JVM 退出与冷恢复，并量测有界候选提交负载。**不修改现有运行服务、归属、历史和周期快照开关；不是完整系统 TPS/自动切主验收。**

## 1. 优化与保护边界

实时去重流的两个固定 JSON 分隔符改成常量字节；小字符串与简单 PResult 使用捕获内复用的 UTF-8 writer。仅对精确 PResult 类、data/totalData 为空、字符串总长不超过 8,192 UTF-16 字符的叶子生效。字段仍由原 fastjson ObjectWriter 编码，不手写结果字段顺序。

运行工具 `com.gateway.connector.utils.JsonUtils` 会开启 `WriteEnumUsingToString` 和默认日期格式。本轮允许零特征或该枚举特征的标量复用（标量叶子不含 enum/date）；引用检测等其他特征、复杂对象、大对象、子类、自定义字符串/结果 writer、filter/mixin 均走原路径，不拒绝旧数据。每条结果后清掉 root；捕获结束关闭编码器，不关闭调用方输出。不引入业务对象 ThreadLocal、完整去重 DTO 表或整快照缓存。fastjson 本身可能给 writer 一个至多 4 MiB 的既有缓存；小叶子限制避免随整个快照增长，复杂单条仍是原分配路径。

分区业务屏障仍覆盖状态捕获、编码、排空、file sync 和替换。实际并发 mutation 阻塞测试证明它不能穿过正在流式捕获的屏障。IO 异常保留原 `JSON.writeTo` 的 JSONException 包装；异常不替换 latest，不放宽格式、恢复预验证、原结果/保留窗口、dirty-tail、复制提交或 READY。

## 2. 测试、产物与计数修正

最终 Java 8 缓存依赖、断网全量为 **70 类 / 377 项**，零失败/错误/跳过；本轮新增 16 项（9 编码/屏障/运行配置、4 TCP 故障、2 进程异常恢复、1 捕获试验预算）。此前聚合目录残留 `TradeRecoveryConfigurationCoverageTest` 的 1 项旧报告，当前源码已无此类；本轮仅统计当前源码对应报告。前一阶段写成 68/362 的源码计数应修正为 **67/361**，镜像内 92 项与真实日志实测不受影响。旧报告保留，不删除或伪称本轮执行。

两次测试准备中发现并修正了 IO 包装差异、实际枚举配置导致全回退的问题；上面的成绩是最终代码重跑结果，不把失败轮计作通过。最终 allocation/copied-journal 主程序初始化相同实际 connector 默认设置，避免只在零配置实验 JVM 里有效。

## 3. 异常与吞吐的实际范围

4 项 TCP 契约使用实际 DirectNetty server/transport、Trade replica handler、Chronicle 文件、coordinator、cash executor 和恢复类：正常两阶段复制/原结果重试；真实交付后应用侧丢失 commit ACK；副本 TCP 停服后禁止降级本地成功；副本更高 epoch 拒绝旧主。故障后不安装未确认资金并撤销 READY，已交付提交恢复后只返回原结果。ACK 丢失使用真实 TCP 成功后应用侧注入，不伪称抓包/网络设备丢包实验。

2 项子进程在成功响应后、或复制提交写完但安装之前调用异常 halt(23)，不执行正常 close。新 JVM 打开主/副本文件，主副两份都恢复到 120，重试 r2 无新增 append/重复入账；主文件从已同步 checkpoint + delta 恢复。两份 journal 原来在同一子 JVM，使用 synthetic assignment/测试 READY，**不是独立节点故障可用性、控制面 promotion 或宿主机断电 RPO 证明**。

有界负载使用单分区候选现金协议、真实 loopback TCP 和两份 Chronicle：每轮 300 个新请求、16 个 worker，排除 1 个连接 warmup；另重试全部 300 个请求，验证余额、主副 seq、快照冷恢复不变。连接、publisher、业务授权和 assignment 是测试 adapter，不含 broker API、下单/撮合、MD/Projection 收敛，所以成绩只能叫 **候选现金提交吞吐**，不能称“系统交易 TPS”。

## 4. 实测证据与晋级门禁

候选镜像 local/tradesvr:snapshot-encoder-5c21a51，ID `sha256:2677fbfd4d8df897c5aeee0112c759842534f10488ed48be5b2adb6a5fea1b53`；生产 revision 为 `5c21a5136cb080325dbba003f580913311e5088b`。后续仅实验 helper/测试提交 `4ae585bb5a12263f4bf1b2ae7b17b90dd4b8b80f`，生产字节码未变。312 文件（232 代码/资源＋80 依赖）全部匹配本地；C locale 清单 SHA256 `b103bd8be75d594c13fa6ec9d3d6727d01659323f37c87f3e831dcc96650e2a0`。比旧 3f0d027 镜像仅 Store 相关 7 文件新增/改变、305 不变、80 依赖相同、无删除。没有推送/部署。

固定镜像断网关键 **9 类 / 108 项**通过，28.379 秒；host 安全测试 **11 项**通过（TIMEOUT 是主动超时 fixture 的预期输出）。

### 真实副本分配与屏障对照

相同标记过的隔离 P204/P122 副本，1 GiB 堆、2 GiB 容器、1 CPU、断网，P122 先常驻。P204 快照 100,473,484 字节，406,870 条 applied 结果、153,741 个 terminal 键。全日志、快照增量与原状态指纹均为 `d92971371930c9d0d67b01bc9c6caa3f7d6052b60de2bc10b35c8817b06a4c1c`。同指纹不证明历史业务正确；缺状态订单/未核实配置未修复，不能据此开启线上快照。

实际 connector 设置的首轮单次对照：旧屏障 **1049 ms**，新两轮 **1705 / 1546 ms**，没有证明新版更快。随后同 helper 4ae585b、同状态连续捕获五次；每次显式 GC 在捕获之外、双方相同。

| 指标 | 旧编码 | 新编码 |
| --- | --- | --- |
| 五轮屏障 ms | 1677 / 1038 / 1088 / 759 / 844 | 1094 / 959 / 816 / 1022 / 880 |
| 后四轮屏障中位数 | 941 ms | 919.5 ms |
| 首轮捕获线程分配 | 382,694,656 B | 77,179,856 B |
| 后四轮捕获线程分配中位数 | 321,250,544 B（306.4 MiB） | 15,490,676 B（14.8 MiB） |

分配中位数减少 **95.18%**；每轮简单结果复用 406,870 次、字符串 560,611 次、fallback 0。线程计数含 pre-scan/少量诊断，不含 GC/native/其他线程，**不是保留状态占用**。屏障中位数仅差 21.5 ms（2.28%）；共享 VM/JIT/IO 波动及之前单次新版更慢，不能宣称稳定停顿、RTO 或线上 p99 改善。首轮和后续轮均保留，不只挑最好轮。

实际默认配置 features=16384、日期格式 yyyy-MM-dd HH:mm:ss 下，合成 10 万条标量交替三轮：旧分配 87,388,768 / 85,600,024 / 85,600,024 B，新 1288 / 216 / 216 B。每轮输出 19,180,361 字节且 SHA256 相同。缓存复用解释小增量，不表示系统零分配；有一轮旧编码耗时更短，不能把短微基准作为稳定速度/TPS 结论。

### 300/16 候选现金提交结果

固定镜像、512 MiB 堆、1 GiB 容器、1 CPU，三轮各新建独立测试文件/loopback TCP。

| 轮次 | 候选现金提交/秒 | p50 | p95 | p99 |
| --- | --- | --- | --- | --- |
| 1 | 101.5 | 5.13 ms | 843.52 ms | 1259.46 ms |
| 2 | 305.7 | 1.07 ms | 339.39 ms | 588.56 ms |
| 3 | 211.3 | 2.74 ms | 391.88 ms | 548.18 ms |

三轮均完成 300 新请求＋300 原请求重试，主副 seq=604、余额=3110；重试不追加/重复入账，快照冷恢复一致。第一遍准备漏挂 fixture 所需 JUnit，NoClassDefFoundError/退出 1；补只读测试依赖后重跑，上表仅成功轮，结构化证据保留准备失败。16 worker 在单分区屏障上排队，尾延迟高；连接 warmup 不等于充分 JVM 暖机。**这是短、有界的合成现金提交吞吐，不是持续容量、系统交易 TPS，未做旧系统同负载性能对照。**

## 5. 运行环境与后续顺序

2026-09-29 20:51（上海）只读核对 Order A/B、Trade A/B、MD A/B/C、Projection 共 8 容器均 running、0 restart/OOM、原镜像。Trade 256 assignment READY；A/B journal 各约 4.2 GiB，堆 768/384 MiB，replication.required=false、周期快照 false。候选两大分区保留状态约 477 MiB，B 384 MiB 无接管资格；READY 不是 API 可写/提交权威证明。

实际现金 API 仍走旧 CashInOutFacade/balanceFacade/recorder 路径，未实例化候选 cash executor；公共有界恢复调度未完成三个服务实际接线。**本轮优化/离线资格验证完成，完整集群异常切换与系统 TPS 未完成。**

后续顺序：

1. 明确独立隔离测试集群，或现有历史审计/迁移路线。不能自动 SQL 补种、重写历史或把旧业务状态当可信基线。
2. 接真实 API 的本地文件权威、完整业务计算/安装/发布与公共有界生命周期 adapter；量测完整节点资源、提交边界和留存/GAP。数据库只做 Projection。
3. 门禁通过后，实际节点/控制面故障检测、旧主 fencing、promotion、恢复、首个成功响应、订单/资金/行情对账，再完整 300/16、持续系统 TPS、负载中故障与长稳。

结构化逐轮证据：[trade-scalar-encoder-and-tcp-qualification-20260929.json](evidence/trade-scalar-encoder-and-tcp-qualification-20260929.json)。保留准备失败、全部单轮/五轮、指纹、分配/耗时、产物身份、候选吞吐、只读健康和未通过门禁。

后续位置更新：本页五份完成的 VM 快照实验输出已可恢复转移到本机工作目录，快照前后 hash 一致、journal 输入不动；原报告路径是历史位置，当前目录映射见 [后续接线证据](evidence/trade-bounded-recovery-integration-20260929.json) 的 archivedOwnLabOutputs。未删实验数据或修改本页原计量结果。
