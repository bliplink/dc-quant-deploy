# 新服务接入 Common 与集群排障指南

更新日期：2026年11月16日。适用于当前 OpenTradingCore 的 Common A/B 自动接管、追平和 Home 自动回主实现。

新服务接入的核心是：**你实现业务状态机，把准备好的状态变化交给 Common 持久化；Common 确认后，你才更新业务状态并返回成功。** Common 负责选主、隔离、WAL、复制、提交水位及恢复，新服务负责业务规则、幂等和业务数据对账。

本文以开发 `AuditSvr` 为例说明接入方式。代码示例展示调用关系；完整运行还需要装配认证、启动与恢复依赖。当前尚无开箱即用的统一 Spring Boot starter，不能只添加 Maven 依赖和几行配置就宣称服务已经具备生产级 HA。

当前参考源码为 Common `f7bb1e4f87ade75449a370738374c8bcaae3aab6`，已验证 JAR SHA256 为 `4a966ced261fe2105cda18782c140717dc1ab0c773ee788a7948243713e1747c`。该版本已通过 Common 完整 P0；Order/Trade 的同版完整业务故障验收和性能目标仍未全部通过。新服务也必须独立验收。

## 一 先理解 Common 与业务的分工

| 工作 | Common | 新服务 |
| --- | --- | --- |
| 成员、租约、Epoch、旧主隔离 | 实现并认证 | 提供身份与配置，遵守授权 |
| WAL、TCP复制、真实落盘确认、提交边界 | 实现 | 提供不透明命令字节 |
| 业务校验和状态变化 | 不解析业务内容 | 实现，并在写入前准备完整变化 |
| 内存状态、索引、去重和业务回执 | 不定义内容 | 实现一致的 apply、快照与恢复 |
| 自动接管、追平、Home自动回主 | 实现 | 提供恢复期间的业务互斥与重放回调 |
| SQL或其它查询投影 | 不替代业务对账 | 维护投影游标，验证源与投影一致 |

正常 A/B 各承担128个 Home Primary、备份对端128个分区。A故障时B接管；A回归后先追平，再通过新Epoch和认证授权自动取回自己的Home分区。B故障时同理。Home是稳定归属，Current Primary是此刻的合法写入节点。

Common内部复制走TCP/Netty。ZooKeeper用于成员、租约和角色控制，业务不应自行每笔查询ZooKeeper来判断可写。见证节点提供当前实现需要的独立认证依据，不等于增加了一个完整业务数据副本。

Mac Demo的A/B运行在同一个Colima中。不同容器和卷能验证进程故障与恢复逻辑，但不能提供两台物理机器的故障隔离。

### 依赖包与版本

当前源码的Maven坐标如下。这是开发用SNAPSHOT坐标，取得依赖后仍需核对完整资格构建的实际JAR SHA，不能把版本字符串相同当作字节相同，也不能假设公共仓库已发布本次候选。

```xml
<dependency>
    <groupId>io.github.bliplink</groupId>
    <artifactId>com.app.common</artifactId>
    <version>3.0.22-t143-durable-signed-crossjvm-handoff-20261026-SNAPSHOT</version>
</dependency>
```

开发接入应使用已冻结并通过资格的完整Common产物，记录源码SHA与JAR SHA，检查最终镜像中没有混入第二份旧Common。正式发布还需要形成不可变版本；本文开头的固定源码与SHA代表当前可核验基线，不能用任意新下载的同名SNAPSHOT替代。

## 二 开发新服务需要准备什么

先明确以下五项，再写适配器：

1. **分区键**：哪些数据必须顺序执行、原子更新。例如按租户分区，或者按租户与品种分区。分区映射必须稳定，不能改Hash规则后直接复用原数据。
2. **命令格式**：包含版本、业务请求ID、分区身份及完整可重放变化。相同请求重试应返回原结果，不能重复产生业务效果。
3. **权威状态**：列出恢复所需的全部状态，包括索引、去重记录、未完成业务步骤和原始回执，而不只是主表。
4. **确认合同**：严格双副本，还是本机落盘后确认、备节点异步复制。API必须让调用者识别单副本风险。
5. **业务对账规则**：恢复后怎样证明没有重复执行、漏执行或跨租户污染；SQL投影应与哪个权威提交游标比较。

Order按租户、市场、品种路由，Trade按租户路由，这是两个不同业务的选择。逻辑撮合队列不一定等于独立Common分区，也不一定等于独立资金处理资源。新服务不要照抄分区键而跳过业务原子性分析。

## 三 日常写入使用哪个接口

业务入口使用 `CertifiedBusinessCommandRegistry`。其中：

| 接口 | 适用场景 |
| --- | --- |
| `commitThenApplyCertifiedWithPolicy` | 普通业务写入，需要把实际持久化模式写进可重放回执 |
| `commitThenApplyCertified` | 同样按已安装模式提交，但编码器不需要接收模式参数 |
| `commitThenApply` | 明确要求严格提交的调用，不会自动变为正常异步路径 |
| `commitBatchThenApply` | 当前已有的严格批量提交入口；不是自动收集请求的批处理器 |

最重要的顺序是：**业务互斥 → 准备变化 → Common持久提交 → 应用确切提交字节 → 返回结果。**

下面示意新服务的业务方法，`domain`中的方法由你的服务实现，`writers`由已经完成认证和重放的Common运行时提供：

```java
// domain.withPartitionMutationLock 必须与同分区的恢复、快照协调互斥。
// prepareAndEncode 只准备变化，不修改真实业务状态，不调用外部服务。
public Object handle(byte[] request) throws Exception {
    final byte[] immutableRequest = request.clone();
    final String partition = domain.partitionFor(immutableRequest);
    return domain.withPartitionMutationLock(partition, () ->
        writers.commitThenApplyCertifiedWithPolicy(
            partition,
            (p, epoch, sequence, policy) ->
                domain.prepareAndEncode(immutableRequest, p, epoch, sequence, policy),
            (exactCommittedBytes, receipt) ->
                domain.applyAndBuildResult(exactCommittedBytes, receipt)
        )
    );
}
```

`receipt`真实字段包括 `partition`、`epoch`、`sequence`、`durability`、`quorumDurable`、`rpoRisk`。业务回执和幂等记录应保存实际模式，重试时返回原来的承诺，不能把原本LOCAL的结果升级成双副本成功。

`applyAndBuildResult`必须应用Common传回的确切字节，不能改用调用方仍在变化的原对象。持久提交后的apply异常会触发隔离与认证重放，不能捕获后继续返回成功。同一提交回调中也不能再次嵌套提交同一分区。

跨多个Common分区、跨多个服务的业务事务，需要业务自己定义合法的步骤、幂等与补偿。Common的单分区提交不自动提供跨服务原子事务。当前Order/Trade的预占、撮合、结算是业务流程，不能作为通用集群代码复制进新服务。

## 四 恢复需要实现哪些接口

### 业务状态机

`ReplicatedStateMachine`的核心方法如下，方法名及类型来自当前源码：

```java
void apply(byte[] command);
void snapshot(ReplicatedStateMachine.ChunkSink sink) throws IOException;
void restore(ReplicatedStateMachine.ChunkSource source) throws IOException;
default void finishReplay() { }
```

- `apply`解释一条已经提交的命令。正常执行和恢复重放必须产生相同业务结果；不要在重放中重新发出付款、发信等外部副作用。
- `snapshot`在Common协调的提交边界捕获完整一致状态，通过分块接口输出。
- `restore`原子恢复完整状态，或失败并保持不可服务。不能只恢复余额而遗漏去重和未完成业务步骤。
- `finishReplay`完成业务恢复收尾；它本身没有发布READY的权限。

### 业务恢复适配器

当前完整自动恢复适配器使用 `CommonCertifiedProductionPhysicalRecovery.BusinessPorts`。业务需提供：

```java
PartitionStateMachineRegistry businessRegistry(
    StateMachineRecoveryCoordinator.RecoveryRequest verifiedRequest);

DurableRecoveryTransactionControl.Barrier exclusiveBusinessMutations(
    String partition);

DurableRecoveryTransactionControl.Readiness denyBusinessUntilReady(
    String partition);
```

注册表只为Common已经认证的目标分区建立业务状态机。业务互斥用于阻止恢复时仍有线程修改该分区；readiness回调用于恢复期间撤销业务可服务证据。它们不负责选主、推进Epoch或宣布READY。

不要使用 `originalJournalBaseline` 的旧兼容入口另开业务日志；当前默认会拒绝第二套journal。主副本恢复的WAL、提交边界和实际网络来源均由Common管理。

## 五 启动和配置如何装配

### 启动顺序

当前Mac正式路径可参考 `OrderCommonFirstReadyE2Wiring`：

1. 装配真实ZooKeeper控制器、节点独立身份、公钥固定目录、网络端点和原始Home证明。
2. 建立同一个 `CommonCertifiedFirstReadyE2NodeBinding`，在启动控制器前接入其认证门禁；不能等到可写后才补恢复检查。
3. 提供业务初始重放、业务恢复证据和上面的 `BusinessPorts`。
4. 调用binding的 `open(...)`，由Common打开真实持久存储、认证状态、启动复制和自动恢复。
5. 取得已认证的 `CommonCertifiedNodeRuntime`，检查运行时及业务重放就绪，再把 `requireCertifiedBusinessRegistry()` 注入业务写入组件。
6. 启动业务入口；关闭时释放运行时和binding。专用单节点进程可使用 `forDedicatedVoterProcess()`，在整个节点被永久隔离后退出，由既有进程管理器重启并认证回归。

`open(...)`目前接收较多路径、身份、网络和业务依赖；应用中的Spring配置负责装配，不能用返回true的假验证器替代。新服务应复用Common实现，不复制Order/Trade的集群协议。初始化空集群也需要真实出生认证和新部署命名空间，空目录不等于合法Genesis。

### 配置示例

下面的 `audit.common.*` 是**新服务需要在自己装配代码中读取的示例前缀**，Common不会自动识别任意业务前缀。当前Order/Trade分别使用 `order.common.*`、`trade.common.*`。占位路径与身份必须由部署程序生成，示例不可原样启动。

```properties
audit.common.control.enabled=true
audit.common.control.zkHosts=zk1:2181,zk2:2181,zk3:2181
audit.common.control.nodeId=AuditSvrA
audit.common.control.manifestPath=/otc/<deployment>/audit/manifest
audit.common.control.leasePath=/otc/<deployment>/audit/leases/AuditSvrA
audit.common.control.ownerToken=<部署生成的本进程独立值>

audit.common.nodeRuntime.enabled=true
audit.common.nodeRuntime.phase=READY
audit.common.nodeRuntime.service=AuditSvr
audit.common.nodeRuntime.automaticRecovery=true
audit.common.nodeRuntime.bindHost=0.0.0.0
audit.common.nodeRuntime.bindPort=28320
audit.common.nodeRuntime.nettyPeers=AuditSvrA@host-a:28320,AuditSvrB@host-b:28320
audit.common.nodeRuntime.dataRoot=/srv/dc/data/audit/A
audit.common.nodeRuntime.snapshotRoot=/srv/dc/data/audit/A/snapshots
audit.common.nodeRuntime.physicalHosts=AuditSvrA@PhysicalHostA,AuditSvrB@PhysicalHostB
audit.common.nodeRuntime.rsaAliases=AuditSvrA@AuditSignerA,AuditSvrB@AuditSignerB
audit.common.nodeRuntime.originalHomeLedgerDir=/srv/dc/data/audit/original-home
audit.common.nodeRuntime.freshE1.namespace=/otc/<deployment>/audit
audit.common.nodeRuntime.freshE1.birthRoot=/srv/dc/data/audit/birth
audit.common.nodeRuntime.witnessRoot=/srv/dc/data/audit/witness
audit.common.nodeRuntime.signedSourceHmacDir=/run/secrets/audit-source-auth
audit.common.nodeRuntime.recoveryWatchMs=200
audit.common.nodeRuntime.snapshotSweepMs=60000
```

还需装配独立私钥、公钥目录、见证身份与回执路径、原始出生和快照证明、恢复读取认证及其余 `open(...)` 参数。B使用自己的nodeId、租约、密钥和可写数据卷。私钥、认证密钥和真实ownerToken不能写入公共文档或Git。

本机专用的 `peerDataRoot` 及 `useReadOnlyReturningPeerVolume(...)` 用于原Mac两个卷的只读回归路径。跨主机部署不能把这个路径当远程复制地址，也不能把两个节点指向同一可写数据目录；需要验证符合该部署拓扑的Common恢复来源。

确认模式由当前运行入口读取的JVM系统属性选择：

```text
-Dcommon.certified.clientAckPolicy=STRICT_QUORUM
-Dcommon.certified.clientAckPolicy=LOCAL_DURABLE_ASYNC
```

A/B必须选择相同模式。当前模式还与部署命名空间中的固定策略校验，不能只改一台进程的参数就热切换策略。Mac入口通过 `MAC_DEMO_CLIENT_ACK_POLICY` 生成对应部署，真实模式仍应核对进程参数、标签及绑定策略。

严格模式正常要求真实双副本提交；备节点故障后，只有完成合法接管或降级授权的单节点路径才允许本机持久确认，并明确风险。异步模式在本机WAL与签名LOCAL提交边界落盘后确认，备节点随后复制。备节点未追平就接管，可能丢失已确认但未复制的尾部；旧主回来也不能直接把被排除的旧尾部塞进新Epoch。

同时监控WAL和多代Snapshot的增长；业务日志轮转不能控制恢复数据的占用。当前Mac已实际发现大量历史快照保留，自动归档／安全清理仍需独立验收。不能仅按文件年龄手工删除当前认证快照或恢复依赖。

数据、日志、身份和出生证明要配置持久存储。日志轮转与普通业务降噪不改变Common WAL；但必须检查**实际容器挂载和实际读取的配置**。本次Mac已发现control目录的日志策略没有进入物理主备配置，并已修复一键部署入口。

## 六 集群故障先看哪几件事

排查顺序是：**版本身份 → 第一个异常 → 当前授权 → 持久提交 → 业务状态 → 投影。** 保留首个异常后再处理，避免大量重试和日志轮转淹没起因。

| 要回答的问题 | 需要的证据 |
| --- | --- |
| 真在运行哪个版本 | 源码SHA、镜像ID、实际Common JAR SHA、容器启动时间与重启次数 |
| 哪个分区先出问题 | 第一次异常的partition、epoch、seq、phase、完整cause与suppressed链 |
| 当前谁有权写 | 认证后的manifest、当前租约、Current Primary、Epoch、READY与隔离状态 |
| 哪些数据已经确认 | 原始WAL、本地强制落盘水位、LOCAL边界或双副本提交水位、前缀与原始签名 |
| 故障是复制还是业务 | 复制积压、业务恢复异常、未完成业务步骤、幂等结果和原始请求ID |
| 查询端是否只是落后 | 源提交游标与SQL等投影的游标、余额、持仓或新服务自己的状态核对 |

`READY`不能单独证明订单已经成交，容器UP不能证明有合法写权限，本机WAL更长也不能单独证明数据已提交。比较水位时必须同时带partition和epoch；不同Epoch的裸sequence不能直接比较大小。

### 可先执行的只读操作

以下基础命令不切主、不修数据；替换为真实容器名。日志先保留在仅自己可读的本地目录，避免将业务内容或密钥上传Git。

```sh
docker ps --format '{{.Names}} {{.Status}}'
docker inspect -f '{{.Id}} {{.Image}} {{.RestartCount}} {{.State.StartedAt}} {{.State.OOMKilled}}' <容器名>
docker inspect -f '{{json .Mounts}}' <容器名>
docker exec <容器名> sha256sum /srv/dc/dc/<服务>/lib/com.app.common-mac-demo.jar
df -h
docker system df
```

最后一条JAR路径是当前Mac镜像的命名约定，新服务要核对自己的实际依赖路径。不要直接打印完整环境变量或整个配置文件，其中可能含身份与认证信息。

Mac现有业务专项只读核验入口：

```sh
cd /Users/kong/dc-quant-deploy
python3 tests/t457_readonly_common_ha_preflight.py --help
python3 scripts/verify-mac-demo-settlement-backlog.py --help
python3 tests/check_certified_trade_financial_cursor.py --help
```

多品种核验可使用结算待办工具的`--all-symbols`，扫描全部256个实际Primary分区；默认模式只观察所选租户的BTCUSDT分区。新版会单列Order-only保留重放记录，并以源码版本命名观察类、核对实际输出版本，避免JVM复用旧诊断类造成误判。

这些工具分别检查当前Order/Trade物理接入、真实Primary的结算待办、资金持仓与认证游标。它们带有现有业务假设，不能不改参数和对账逻辑就用于任意新服务。诊断工具版本也要保留；旧工具不支持新证明格式时，不能把工具报错直接当成数据坏了。

### 常见现象及下一步

| 现象或日志 | 下一步 |
| --- | --- |
| JAR或节点身份不一致 | 先修构建、镜像、挂载或身份装配，保持同一完整资格版本 |
| `COMMON_COMMIT_PHASE` | 看phase及`walWriteStarted`，追到原始异常；前置拒绝与写入后的未知结果处理不同 |
| `COMMON_ASYNC_BACKPRESSURE_BEFORE_APPEND` | 检查备节点可达性、复制积压、工作线程和磁盘；保留未追加的拒绝，不扩大队列掩盖故障 |
| `COMMON_ASYNC_DRAIN_UNAVAILABLE_BEFORE_STRICT_OPERATION` | 严格读取或操作在等复制完成；核对复制水位及对端首错 |
| `COMMON_ASYNC_REPLICATION_FAILED` | 保留该分区的第一条异常和原始证据，确认合法角色变化与现有自动回归是否继续 |
| `FATAL_COMMON_NODE_EPOCH_FENCED` | 原节点已失去该Epoch权限；专用进程退出后由既有管理器重启并认证恢复，不能让旧Epoch继续写 |
| 停在RECOVERING或无法回主 | 核对源数据认证、快照及WAL范围、提交边界、业务restore/apply首错、回归证明和原始Home |
| WAL CRC、前缀或签名不符 | 保留两端原件并拒绝危险写入，追查损坏或错误来源；不能手改水位或关闭校验 |
| 资金已变但最终回执未发 | 分别核对资金提交、持久撮合交付、原回执模式、Order本地终态与复制确认；不能重复结算来补回执 |
| SQL看起来少数据 | 先比投影游标与权威源；区分暂时追赶、业务漏apply和源数据问题 |
| 延迟高但平均CPU低 | 检查提交锁、业务锁、磁盘强制落盘、签名、GC、复制等待及发生器排程；平均CPU低不能排除串行瓶颈 |

需要线程录制、JFR或故障注入时，单列诊断窗口，与正式性能验收分开。不要把跨线程等待总和当作单笔延迟，也不要把只收到的部分回执P99说成整个请求群的尾延迟。

### 实例：业务持续报背压，Order 主节点消失后接管停住

在 11 月 16 日的演练中，Order A 退出后，Order B 的业务日志持续报异步写入背压。检查时先按分区统计主节点、Epoch、策略和 READY 状态，再看 RECOVERING 分区的最近一次恢复拒绝原因。P162 是存活的 B 原本负责的分区，它在首次备份复制前已经确认了 64 帧本机数据。旧版本在读取完整空累计提交文件时要求获得一条双副本提交记录，导致这个分区停住。其他分区反复等待该分区完成。

这个场景要分清谁还持有原始数据。原主存活时，在副本上看不到提交记录，仍应核验原主已签名的本机边界、签名退役记录和原 WAL。原主失联且备节点接管时，才适用备节点已复制水位。修复在文件副本上用新旧 JAR 对照重放，再走 Common 和业务演练。原始证据、未确认尾部、Stage 和 Epoch 均保留。完整数据和状态见[集群机制审阅](/Users/kong/dc-quant-deploy/docs/T554_CLUSTER_MECHANISM_REVIEW_20261113.zh-CN.md)。

## 七 找到问题后如何修复

**配置或部署问题**：修正确切的身份、端点、文件权限、磁盘空间、持久挂载或镜像，再验证实际进程确实读到修复。重启应有明确原因和计划，不能用连续重启覆盖原错误。

**业务问题**：如果是命令不完整、幂等遗漏、快照缺字段、apply或重放错误，在对应服务修复并测试。先证明旧源码会失败，再验证修复后的正常执行、快照重放和重复请求。Common不应加入你的订单、余额或审计记录类型分支。

**Common机制问题**：先冻结候选JAR，在Demo/Common复现，修复通用机制并通过完整P0。随后把完全相同SHA的JAR接入业务，先基础业务、再真实业务故障门禁。不能在Order和Trade分别添加各自的选主或恢复补丁。

**开发环境需要重建**：先保留最小故障证据、源码身份与原始失败结果，按已授权计划顺序重建新命名空间、重新认证出生，再走真实业务。新安装成功不等于旧数据自动恢复成功。生产数据修复需要明确恢复来源和数据合同，不套用Demo丢弃重建方式。

Mac现有完整资格入口为：

```text
python3 scripts/qualify-mac-common-candidate.py <冻结候选目录> <新的结果目录>
bash mac-colima-saas.sh fresh-verified <已通过候选目录> <对应完整资格结果目录>
```

第一条运行Common私有故障验收；第二条会顺序替换当前Demo业务部署。它们是主动验证与部署操作，**不是只读排障命令**，也不能在正式性能窗口中同时运行。

修复完成的判据：A/B两个方向持续业务下故障接管、单节点合法处理、回归追平、自动Home回主、旧主隔离、原始持久字节及业务对账都通过。性能再分别验收严格和异步、多租户与多品种，统计真实完成数、失败、缺失、窗口外完成和端到端P99。当前项目第一阶段目标是持续1000笔/秒、P99不超过20毫秒、至少60秒。

## 八 源码阅读顺序

以下链接指向本机当前源码，阅读顺序从业务接口到运行时。先看前四项，再沿真实装配类进入Common内部，不必一开始遍历所有恢复类。

1. [业务写入与确认接口](/Users/kong/.opentradingcore/t525-common-latest-20261106/src/main/java/com/app/common/replication/CertifiedBusinessCommandRegistry.java)
2. [业务状态机接口](/Users/kong/.opentradingcore/t525-common-latest-20261106/src/main/java/com/app/common/replication/ReplicatedStateMachine.java)
3. [Order业务恢复适配器示例](/Users/kong/dc-quant-deploy/.work/t545-default-exec-validation/src/main/java/com/app/dc/service/state/OrderCommonRecoveryBinding.java)
4. [当前Mac运行时装配示例](/Users/kong/dc-quant-deploy/.work/t545-default-exec-validation/src/main/java/com/app/dc/service/state/OrderCommonFirstReadyE2Wiring.java)
5. [Common共享启动入口](/Users/kong/.opentradingcore/t525-common-latest-20261106/src/main/java/com/app/common/replication/CommonCertifiedFirstReadyE2NodeBinding.java)
6. [Common提交与apply边界](/Users/kong/.opentradingcore/t525-common-latest-20261106/src/main/java/com/app/common/replication/CertifiedBusinessCommandBoundary.java)
7. [当前集群机制及性能审阅](/Users/kong/dc-quant-deploy/docs/T554_CLUSTER_MECHANISM_REVIEW_20261113.zh-CN.md)
8. [Common业务边界约束](/Users/kong/dc-quant-deploy/docs/ARCHITECTURE_SIMPLE_COMMON_BOUNDARY_20261029.zh-CN.md)
9. [A/B自动回主架构](/Users/kong/dc-quant-deploy/docs/COMMON_AB_HOME_PRIMARY_AUTO_FAILBACK_ARCHITECTURE_20261031.zh-CN.md)
