# Mac 10 户 MD-C epoch-fence 候选恢复（2026-10-12）

## 实际完成

冷部署的新集群中，MD A/B/C 原来均采用同 Common
`361e3e3` 的 `bcdec888` 基线；但是更晚的 MD
修复提交 `dff97ba95a4ae29062e9e353680c79e84d38e8f4`
含新 epoch 发布栅栏、完整镜像重放 witness 和 queued
publish 二次验证，未包含在基线中。

Mac 中用原 `bcdec888` 的独立离线源码构建目录，对比
`bcdec888..dff97ba`，只移入 7 个真实被修改的源码与
单元测试文件，保留统一的 Common 361 Maven 依赖。
Java8 Maven **130/130 单元测试通过**，0 fail、0 error。
构建并检查镜像：

`dc-saas/mdsvr:cluster-dev-local-md-epoch-fence-dff97ba-c361e3e3-20261012`

Common JAR SHA256：
`0ed677b3c57bf65664c209c150570a598b1a9db7a82e63a694e1fe926bf003f3`。

部署只作用于 ZooKeeper 中**没有任何 Primary 分区**的
`MDSvrC`；MD A/B 各保留 128 个 Primary，Gateway
仍使用原先的业务透传镜像，没有修改 Order、Trade、
MySQL 或业务配置。

保留原 `dc-saas-mdsvr-c` 的容器 ID/镜像记录，执行
`docker compose -f compose.yaml -f <md-c-overlay> up -d --no-deps --force-recreate --no-build mdsvr-c`
（须传入 Mac 私有 `fresh-release.env` 并启用
`md-cluster-c` profile）。
有独立原镜像 overlay 作为单节点回滚，不清理 MD 数据。

部署后实际验证：

- MD-C 新容器 RUNNING、RestartCount=0、OOM=false；
- A/B 原容器未重启，MD ZK 256 分区均 READY；
- ZooKeeper 临时成员：
  `MDSvrA=true,MDSvrB=true,MDSvrC=true`；
- MD-C 日志对 **10 个租户**都出现
  `MD_MARKET_READY ... role:LEARNER`，
  确认它已从 Order 订阅重建这 10 个市场；
- 单独新一轮 `check-demo-tenants-readonly.py`
  返回 **10/10 PASS**，机器人仍 40 活动委托和十档双边盘口。

回滚与现场证据只保存在私有目录：
`~/.opentradingcore/local-ha-clean-20261012-v1/`
中 `md-c-epoch-fence-original-overlay.yaml`、
`tenant-before-md-c-epoch-20261012.json`、
`tenant-after-md-c-epoch-20261012.json`、
`md-HA-post-epoch-fence-canary.json`。

## 尚未通过的风险门禁

只读 `scripts/check-md-failover-preflight.py` 的最新结果
`decision=BLOCKED, canPromote=false,
canInjectMdPrimaryFault=false`。
不是因为 MD 应使用自身 WAL 来追平，而是
**Order 最新完整市场镜像见证尚未独立认证、
旧 MD 发布主的可靠 fence 尚未端到端验证、
新 epoch market-image 和 Robot 重建未执行故障验收**。
因此 MD-C 虽可充当 Learner，不能强制启用
MD 自动主切或 SIGKILL 任何运行中的 MD Primary。

请勿将此 **本地 macOS 开发镜像**误当成 GHCR 最新
跨平台发布镜像，勿以此作为 200 租户压力认证。
