# Trade A/B · P090 自动互切实机激活清单

范围：Mac mini Demo、saas-crypto、先 P090 自动追平。本文不存储任何实际 RSA 私钥或账号凭证。
目标：SIGKILL A → B 自动接管 → A 自动安装当前 Snapshot/WAL 并提供真实物理 ACK → SIGKILL B → A 自动接管 → B 自动追平 → 完成资金/持仓/委托/成交/Projection 一致性核验。

## 当前现场检查（2026-10-17）

- P090 由 Trade-A Primary、Trade-B Replica，ZK Epoch1/version0、READY。
- Trade 双容器统一 local/dc-saas-tradesvr:ab-nonzero-rejoin-promotion-402-20261017；Docker host 网络、复制端口 A=19221、B=19222。
- 真实 Netty Source HEAD / signed Manifest 验证成功，旧 ZK version 被拒绝；这不是恢复安装。
- autoWarm、物理回执、物理健康认证仍关闭。ZK 复制健康证明为 0/256。故障节点不能自动追平，禁止第二次 SIGKILL。

## 前置身份：必须经过允许的 Mac 安全配置渠道

Trade-A 的源 HEAD RSA 私钥已配置，Trade-B 对 A 的源公钥已配置。
Trade-B 的 Replica 物理签名私钥已配置，Trade-A 对 B 物理回执的公钥已配置。
缺失：Trade-B 自己的源 HEAD RSA 私钥与 Trade-A 验 B 源 HEAD 的公钥；Trade-A 自己的 Replica 物理签名私钥与 Trade-B 验 A 物理回执的公钥。
这些是两个独立物理节点的角色，不可以用 A 的私钥冒充 B，也不能用假 ZK ACK 或手动改主代替。不得发送私钥到聊天或提交 GitHub。
此前受信身份配置被执行环境安全检查拦截；不得切换其他工具或其他路径绕过。未获得允许的配置通道时必须停在此门禁。

## 非凭证配置（受信密钥已设置后再启用）

Trade-A、Trade-B 都要求以下属性：
trade.cluster.recovery.replica.autoWarm.enabled=true
trade.cluster.recovery.replica.electedBootstrap.enabled=true
trade.cluster.recovery.replica.electedBootstrap.fleetEnabled=false
trade.cluster.recovery.replica.autoWarm.pilotPartition=P090
trade.cluster.recovery.replica.genesisReceipt.enabled=true
trade.cluster.recovery.replica.physicalReceipt.enabled=true
trade.cluster.recovery.replica.physicalHealth.enabled=true
trade.cluster.recovery.replica.physicalHealth.fleetEnabled=false
trade.cluster.recovery.replica.physicalHealth.pilotPartition=P090
trade.cluster.recovery.genesisObserver.enabled=true
trade.cluster.recovery.genesisObserver.fleetEnabled=false
trade.cluster.recovery.genesisObserver.pilotPartition=P090
trade.cluster.recovery.genesisObserver.replicaHealthEnabled=true
trade.cluster.recovery.genesisObserver.transferEnabled=false

注意：本轮新增物理 ACK observer 的 pilot/fleet 隔离参数。如果 physicalHealth.fleetEnabled=true，则 Observer 不再只检查 P090，而会按配置轮询整个 256 分区。P090 验收必须保持 false；缺失 physicalHealth.pilotPartition 时新代码拒绝启动，不再静默扫描整个集群。

Trade-A 源和回执目标：
trade.cluster.recovery.replica.autoWarm.sourceNode=TradeSvrB
trade.cluster.recovery.replica.autoWarm.sourceHost=127.0.0.1
trade.cluster.recovery.replica.autoWarm.sourcePort=19222
trade.cluster.recovery.genesisObserver.targetNode=TradeSvrB
trade.cluster.recovery.genesisObserver.targetHost=127.0.0.1
trade.cluster.recovery.genesisObserver.targetPort=19222

Trade-B 源和回执目标：
trade.cluster.recovery.replica.autoWarm.sourceNode=TradeSvrA
trade.cluster.recovery.replica.autoWarm.sourceHost=127.0.0.1
trade.cluster.recovery.replica.autoWarm.sourcePort=19221
trade.cluster.recovery.genesisObserver.targetNode=TradeSvrA
trade.cluster.recovery.genesisObserver.targetHost=127.0.0.1
trade.cluster.recovery.genesisObserver.targetPort=19221

head.enabled、manifest.enabled、data.enabled 和 certifiedRecipient.enabled 两端原本已开启，保持不变。不要动 Gateway、TLS 或 GitHub Actions。

## 执行的 P090 门禁

从 dc-quant-deploy 工作树执行以下命令；其中 DEMO_ROOT 是当前 Demo 运行根目录：
python3 -m unittest tests.test_trade_ab_auto_ha_preflight -v
python3 tests/trade_ab_auto_ha_preflight.py --mode pilot --partition P090 --config-root "$DEMO_ROOT/control/overrides"

要求同时看到 Trade-A P090-pilot-config=READY_FOR_LIVE_PROOF 和 Trade-B P090-pilot-config=READY_FOR_LIVE_PROOF，且两端真实随机挑战验签成功。配置门禁通过只是准许进入实机故障测试，不等于健康或账务验证通过。

## 真实互切流程与停止规则

1. 启用上述经授权且已配对的两端身份及非凭证参数，重新创建两个 Trade 容器，核验正常运行、P090 READY、无启动错误。
2. 记录 P090 两端真实 Snapshot/WAL、ZK owner、Epoch、版本、实际资金和持仓基线。注意 SIGKILL Trade-A 是进程级故障，会同时影响该进程其他约128个 Primary，P090 pilot 只表示先处理该分区的自动追平。
3. SIGKILL Trade-A（不是脚本修改主节点），等待控制器把 P090 自动切换为 Trade-B Primary/Epoch2；检查故障期间真实交易响应。
4. 恢复 A 进程；核验 A 自动封存旧 Epoch 原始 WAL、经 Common 下载并安装 B 当前 Epoch Snapshot/WAL，产生 REPLAY_COMPLETE、真实 RSA 物理 ACK，并由 B 验证发布精确 ZK P090 健康证明。
5. 只有步骤4有实际健康证据才能 SIGKILL Trade-B；此时验证 A 自动升为 Epoch3 Primary，恢复业务 READY 且不丢已提交记录。
6. 恢复 B 并对称验收 B 自动追平 A，重复一次完整反向流程。
7. 对账 Trade/MySQL/Projection 资金、持仓、委托、成交、watermark，确保无丢单、无重复成交、无双主。P090 成功才扩展全256分区和持续压力场景。

若步骤4失败，不要再杀 Trade-B；Demo 可清空重部署，但清空/重建绝不是故障节点自动追平。任何未授权密钥操作安全检查仍拦截时立即停止。