# T449–T450｜Common ZK 客户端自动重连与持续财务投影验收（2026-11-03）

## 边界与根因（T449）

- 旧 `GwClient.ClientConnectionEventListener` 对 TCP `CONNECTION_CLOSED` 调用旧连接 `dispose()` 和断开通知，但仅对非 ZK 注册服务（`!serviceInfo.isRegisterEnable()`）调用 `reconnect()`。ZK 注册的 Order/Trade/MD 节点原地址、端口再次可用时，旧缓存可能阻止重连。
- `GwClient.zkServerInfo` 在节点被 ZK 移除时只 `dispose()` 旧连接而不清除 `htConnection` 缓存，重新注册同地址时可能被 `containsKey` 阻止。
- **修复位置在 Common 的 RPC 客户端，不改变 Gateway 透传机制，不在 Order/Trade 引入业务集群实现。** 上一版 Gateway 的 `GWApi.ConnectionCycle` 已存在，不应误将该功能缺失当作根因。

## 已提交源码

- 仓库：`bliplink/com.app.common`，统一分支 `saas-crypto-latest`。
- 提交：`2531b3a53251008e087666b5afcb0888576b7600`（`[skip ci]`；无 GitHub Actions 构建）。
- `src/main/java/com/gw/common/utils/GwClient.java`：
  1. TCP 关闭时，按原连接对象身份清除缓存（`ConcurrentHashMap.remove(key,old)`），防止迟来的旧回调删除新连接；
  2. 只要仍在最新 ZK 成员列表（`workSet`）中，自动把同地址节点加入连接队列；
  3. ZK 已撤销、进程已 dispose 或旧连接不是当前对象时不复活它；
  4. ZK 服务移除时清除失效连接表，不能在未来重新注册时复用陈旧条目。
- 新增 `GwClientRegisteredRejoinTest.java`，4 项验证：同地址重连、ZK 撤销禁止重连、旧连接迟到事件隔离、撤销时立即清理缓存。
- Mac 本地 Maven `mvn -o -q test`：**705 tests，0 failure，0 error，72 skipped**。4 项新增测试均通过。注意部分测试产生非致命本地配置 WARN，但 Maven exit 0。

## Demo 真实部署与断线试验

- 候选 Gateway 镜像：`local/otc-t449-gateway:common-zk-rejoin`。仅覆盖编译的 Common `GwClient` 相关 5 个 class，其余仍来自 `local/otc-t252-gateway:sha-31b9e15bd7ee`。
- 原 Gateway `otc-t399-gateway-config-t398` 已停止并保留；新 Gateway `otc-t449-gateway-common-rejoin` 成功启动，连接 Order B、Trade B、MD A/B，订阅 `cycle:1`。
- 在**完全没有重启 Gateway** 的情况下，真实执行 `docker restart -t 12 otc-t446-mdsvr-b-querysymbol`。
- Gateway 在 **2026-11-03 00:12:33 +08:00** 检测到 MD B `Host:127.0.0.1,Port:33043:CONNECTION_CLOSED`；MD B 再次启动、ZK 注册、恢复分区后，Gateway 在 **00:13:28.933** 出现 `MDSvrB onConnected,subscribe:[**],cycle:2`。
- 证明 **Common ZK 注册 RPC 客户端对 MD B 真实断线 → 同地址自动重连 → Gateway 自动重新订阅** PASS。并不等于 Order/Trade 全 HA 已通过。

## T450 待接线与持续运行（2026-11-03 06:41 +08:00）

- Order 候选镜像 `local/otc-t450-ordersvr:common-zk-rejoin` 已在 Mac 本地构建成功，基底为 `local/otc-t444-ordersvr:windowed-e2-v2`，加入相同 Common `GwClient` class。
- **未实际替换 Order B**：仍运行 `otc-t444-order-b-windowed-v2`。Trade A/B、MD A/B、Robot、Gateway 与 Projection 均运行无 OOM；Trade B 当前仍为 `otc-t445-trade-b-md-ingress`，尚未接入新 Common class。
- `DAYWUB` 实际 DB `dc_tenant_robot`：`RUNNING`，活动挂单数 **40**，最新 heartbeat 仍正常更新。
- Trade P144 Projection 水位与金融 ReadModel 游标在 06:41 当时均为 **58937/58937**，差值 0；P129/P238/P240/P242 的水位也逐分区一致。余额、仓位持续按成交更新，说明 T448 恢复后经过数小时仍在推进。
- 随后针对 Order B 的 Docker 检查命令被执行环境安全检查拦截；**本轮不能声称 Order/Trade 候选已经替换或重连测试已经通过**。禁止通过重启 Gateway 替代服务自动重连验证，也禁止无证据地强制重建/清空数据。

## 下一门禁

1. 首先确认 Order B 与 Trade B 实际容器运行参数、数据卷/网络，保留旧镜像和旧容器。
2. 受控替换 Order B，验证 Gateway 不重启时的 `OrderSvrB cycle:2`、分区/Replica 恢复、委托不丢单不重单；再对 Trade B 用相同 Common overlay 执行真实重启与订阅恢复。
3. 检验 `DAYWUB` 实时 MD 标记价、Robot 40 挂单、真实撮合成交、`dc_trade_projection_watermark` 和财务 ReadModel 持续追平。
4. 验证 Trade A/B、Order A/B 自动双向主切，以及旧 Epoch 拒写、真实 CommitIndex/WAL 认证、水位/资金/持仓/委托/成交与 Projection 一致性。在全部完成之前，HA **NO-GO**。

**当前结论：Common 源码回归 PASS；Gateway→MD B 自动恢复实测 PASS；Order/Trade 新 Common 接线及全链 HA 仍未完成。**
