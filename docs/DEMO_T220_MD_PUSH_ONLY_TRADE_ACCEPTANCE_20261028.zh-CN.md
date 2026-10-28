# T220｜Trade 仅首次 Image、持续 MD Topic 推送验收（2026-10-28）

## 业务契约
- APSsvr 默认通过本机代理订阅币安合约 `@markPrice@1s`，每条交易所更新立即交给发布组件；自定义价格仍按租户数据源处理。
- TradeSvr 通过 Common `MDSvrClient` 订阅**逻辑 MDSvr 服务**的 `dc.md.trade.{security_id}.{location}` Topic，而不是在业务代码中订阅 Gateway。Gateway/Netty 仅为底层传输实现，不能成为价格业务源。
- **首次订阅**读取一次所属分区的权威 MD Image；以后缓存只由 MD 通知回调更新。
- Order/风险读路径只读取本地缓存，绝不因缓存缺失或超过 TTL 再请求 Image，也不增加 500ms 睡眠。
- 过期/无效标记价格继续 fail-closed；禁止回退 LastPrice。网络重连/MD 分区主切需由 Common 订阅层处理，不能由每笔订单触发重复拉取。

## T220 源码
- `.work/tradesvr/src/main/java/com/app/dc/service/price/MarketPriceFacade.java`：移除 `scheduleMarkPriceRecovery`、按 10 秒重订阅、500ms sleep；每市场通过 `subscribedMarkets` 首次登记，之后靠被动 Topic 更新。
- `.work/common/src/main/java/com/app/dc/utils/MDSvrClient.java`：实时 Topic 订阅至 `SERVER.MDSvr` 逻辑服务，由 Common 分区路由展开到当前 Primary；**首次**权威 Image 单独按 location+market+symbol 路由到物理 Primary。SDK 进程级 V2 Filter 仍按已订阅的租户 Topic 分发。
- 回归：Trade `MarketPriceFacadeTest` + `MarketPriceFreshnessPolicyTest` **4/4 PASS**（含缓存过期不得请求 Image、下一条 MD push 恢复）；Common `MDSvrClientTest` + `MDSvrClientIngressTest` **9/9 PASS**。
- Demo 镜像：`local/otc-t220-tradesvr:push-only-md-topic`，对应 `compose.t220-trade-push-only.yaml`，Trade A/B 已分别滚动部署，均 running、restart=0，并通过 E2 签名冷恢复与 Common Gateway 服务发现。

## 真实运行检查
- 测试租户 `R0F6CC/BTCUSDT` Robot `t199-signed-live` 临时启用，看到 `RUNNING`、2 个活动委托。
- Trade A 从 10:24:49 起约 1 分钟内 **MD 逻辑订阅 1 次、MARK_PRICE_IMAGE_RETRY 0 次、首次订阅失败 0 次**；在 10:24:50—10:26:04 的多次 Newing 返回 code=0。公开 MD 盘口可查到买卖挂单。
- 新版本 Trade B 启动后出现独立阻塞：Newing code=1003 `TRADE_COMMON_NEWING_CERTIFIED_COMMIT_DENIED`，`Common physically certified partition writer unavailable: P246`，最初观察 127.0.0.1:44223 refused；之后复制监听端口可见，但 writer 状态未自动恢复。
- 10:28:42 只读 WAL 审核：Order P089 A/B 各 1398 帧，字节一致；Trade P246 A 113 帧、B 112 帧，**B 是 A 的真前缀但未追平**。禁止删 WAL、截断、强行复制或宣布 HA PASS。
- 总结：**MarkPrice 订阅模型修复 PASS（Trade A 首次镜像+推送模式的功能验证）；真实持续交易/Trade A/B HA NO-GO**。后续优先处理 Common B 重启后 2/2 认证 writer 连接与 WAL 追平，再恢复 Robot 稳定新单与完整 E2E，最后做自动互切。

## 部署注意
- 使用项目运行时完整 Compose 配置叠加链，保留原 A/B RSA 只读挂载。不要单独使用最基础 Compose 重建 Trade，避免丢失 RSA 挂载导致启动失败。
- 没有使用 GitHub Actions，没有修改或清理现有 WAL。
