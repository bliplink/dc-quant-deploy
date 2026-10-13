# MD-C Learner ARM64 灰度记录 — 2026-10-13

## 版本和部署范围

- 分支：saas-crypto。
- MD 恢复校验修复：63d25e351427004ff1194c6ccd4ea5c2df316323；本地 MD 全量测试 136/136 通过。
- GHCR 版本记录：026306b1b311c41bff12c9296cef667e681a7688。
- 仅 MDSvrC Learner 更新为 ghcr.io/bliplink/mdsvr:sha-026306b；A/B Primary、Order 和 Gateway 未重建。
- ARM64 OCI manifest：sha256:3f02b5359dbc17e9123ac0cec49f2f98225bff5ce87d295548dac5cd0452abf3。
- ARM64 Docker 配置 ID：sha256:5ae7d0479d6cb335dc24dfc3f65947b13733fe99b9e28587835dff87a07c4c3a。
- 镜像 common GAV：io.github.bliplink:com.app.common:3.0.19。
- A/B 原镜像：dc-saas/mdsvr:cluster-dev-local-c361e3e3d-20261012034946。

## 验收证据

证据文件：evidence/md-c-arm64-026306b-readonly-preflight-20261013.json。
脚本：scripts/check-md-failover-preflight.py。
新版本只允许精确的镜像标签、ARM64 Docker 配置 ID、源码 Revision、common 版本同时匹配；拒绝浮动 latest 或未审镜像。

- 256/256 分区 READY，未就绪 0。
- A 128 / B 128 Primary，C 保持 Learner。
- A/B/C ZooKeeper 临时成员节点全部有效。
- 逐项与升级前比较，五项晋升阻断理由一致；没有新增镜像/分区异常。
- MD-C running，重启次数 0；交易终端及租户管理外网 HTTP 200。
- MD 自动主切仍 BLOCKED。只读检查退出码 2 是故意设计，并非成功授权晋升。

## 下一步

1. Order 源端可认证持久提交 HEAD、完整市场 Image 与连续 Delta 的真实控制端口接口及跨节点证明。
2. MD 严格验证完整市场恢复后，独立证明 RECOVERING→READY。
3. 完成旧发布者 fencing、共享 Epoch 隔离、ZooKeeper CAS 安全切换；Gateway 仍只做透传。
4. Robot 故障后的 Order 与市场数据权威一致性核验。
5. 前述验收通过后，才执行独立测试租户的 MD Primary SIGKILL、行情连续性、无旧 Epoch 发布、恢复与角色反转。

本次未执行资金划转、交易、删除数据、HA 故障注入或性能压测。
