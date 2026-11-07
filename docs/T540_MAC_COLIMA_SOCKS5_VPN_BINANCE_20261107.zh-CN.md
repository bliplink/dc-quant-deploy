# T540｜Mac Colima 使用本机 VPN SOCKS5 接入 Binance Futures（2026-11-07）

## 结论

用户明确要求 **Docker/Colima APSSvr 的 Binance 外部行情必须经 Mac 本机 VPN 代理**。已确认代理为 Mac Xray SOCKS5，监听 `*:10808`，Colima 内可通过 `host.lima.internal:10808` 访问。不能从容器使用 `127.0.0.1:10808`（那是容器/Colima 自己的 loopback）。

截至本轮，**代理链路已通，Binance Futures 行情仍 NO-GO**：容器使用此 SOCKS5 访问 Cloudflare 返回 HTTP 200，访问 Binance `https://fapi.binance.com/fapi/v1/time` 返回 **HTTP 451**；代理出口到交易所受限，不能据此声明 WS/盘口/Robot/Tape 成功，也不能绕过地域或服务条款的限制。

## 根因和完整证据

1. 旧隔离 `otc-t535-fresh-apssvr-custom` 专门用于 Broker CUSTOM 价格测试，配置 `enableBinanceFlag=false`，本不应作为新租户默认 Binance 行情源。旧 T539 Binance 启用测试报 `java.net.UnknownHostException: fstream.binance.com`，而其 APSSvr 未使用正确 SOCKS5 代理。
2. Mac DNS 通过 `192.168.31.1` 返回非预期 IP：`fapi.binance.com=66.220.149.18`、`fstream.binance.com=31.13.94.23`。Colima DNS 亦来自 `192.168.31.1`，容器直连无法正常解析/握手。DNS 不作为可信行情来源。
3. Mac `xray` 监听 `10808`，实测 **SOCKS5** 可用、HTTP CONNECT 方式不适用。原 `.env.prod` 曾设置 `APSSVR_EXTRA_JAVA_OPTS=-Dhttp.proxyHost=192.168.5.2 -Dhttp.proxyPort=10808 -Dhttps.proxyHost=192.168.5.2 -Dhttps.proxyPort=10808`，错把 SOCKS5 端口配置成 HTTP 代理。
4. 通过 Colima 实际运行中的 APSSvr 容器调用 `curl --socks5-hostname host.lima.internal:10808`，`www.cloudflare.com/cdn-cgi/trace` 返回 200，`fapi.binance.com/fapi/v1/time` 返回 **451**。经 Mac 代理查看返回响应头为 CloudFront 451，`x-amz-cf-pop: LAX53-P3`；不能断言一定是币安还是中间出口策略，但此出口无法取得 Binance Futures 有效数据。
5. APSSvr 现有 Java `BNFuturesImpl.resolveBinanceProxy()` 仅支持 `Proxy.Type.HTTP`，无法正确使用 Xray SOCKS5。Binance Futures SDK `binance-futures-connector-java-3.0.6` 的 `HttpClientSingleton.getHttpClient(ProxyAuth)` 为 OkHttp 客户端，`WebSocketConnection` 也缓存共享的客户端，因此必须在构造 WebSocket 前按 SOCKS5 初始化。

## 已实施的修复

- **APSSvr 源码** `bliplink/com.app.dc.apssvr` 的 `saas-crypto` 分支：新增显式 `APSSVR_BINANCE_SOCKS_HOST` / `APSSVR_BINANCE_SOCKS_PORT`，优先使用 `Proxy.Type.SOCKS` 并用 unresolved proxy 地址，校验 1..65535 端口，配置 `HttpClientSingleton`，兼容原 `https.proxyHost/http.proxyHost` HTTP 代理设置。代理只作用于 Binance Futures SDK REST/WS，不作用于本机 Gateway、MySQL、ZooKeeper、Common。
- **一键部署** `bliplink/dc-quant-deploy:saas-crypto-latest`：`compose.yaml` 向 APSSvr 单独传入两个可选环境变量，`.env.example` 描述 Mac Colima 使用 `host.lima.internal`、Docker Desktop 使用 `host.docker.internal`。其他服务及容器不强行注入 `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY`。
- Mac 本地私有 `.env.prod` 已设置 `APSSVR_BINANCE_SOCKS_HOST=host.lima.internal` 与 `APSSVR_BINANCE_SOCKS_PORT=10808`。已经**删除该文件中旧的四项 HTTP 代理 Java 参数**，不更改其他账号密码；环境权限 0600。私有文件不上传 GitHub。
- APSSvr 单元测试涵盖旧 HTTP fallback、SOCKS5 优先/未解析地址、非法配置拒绝，以及 SDK REST 和 WebSocket 共享同一 SOCKS5 客户端；在本机现有 JDK 8 与缓存依赖下显式指定 Lombok 处理器 `javac` 编译 **PASS，JUnit 11/11 PASS**。本机没有 `mvn`，因此此项是隔离源码编译 + JUnit，不等同于完整 Maven package 或 Docker 镜像发布。
- 新增部署侧 `tests/test_apssvr_binance_socks_wiring.py` 4 项静态回归，并接入 `tests/test-mac-colima-saas.sh`；标准 Mac 回归、`docker compose config -q` 与 `git diff --check` 全部 PASS。

## 上线/真实交易验收门禁

目前运行中的 T535 **Broker CUSTOM APSSvr 旧镜像未更换**，且 `enableBinanceFlag=false`；T539 Binance 候选已停止并回退。**仓库源码接线与 Mac 私有配置变更不会自动给旧镜像增加 SOCKS5 能力**。

在获得有权提供 Binance Futures 行情的可用 VPN 出口后，先从 Colima 容器检查 `curl --socks5-hostname host.lima.internal:10808 https://fapi.binance.com/fapi/v1/time` 返回实际有效响应（不是 451），再从完整构建的新 APSSvr Docker 镜像检查实际 `Binance connector SOCKS proxy configured` 日志、真实 WS 订阅事件与盘口价格更新；最后检查 `dc_tenant_robot.runtime_status=RUNNING`、双向持续报价、Tape 成交、Order/Trade/Projection/资金一致性。若出口继续 451，保持 NO-GO，不能伪造或使用过期数据；可用已有租户隔离的 Broker 自定义价格/数据源机制完成独立测试，但不可默认为 Binance 数据。

不改动 Common/Order/Trade 集群；不执行 GitHub Actions；不复写历史签名 WAL/旧业务数据；不要为了测试自动更换用户当前 VPN 路由或配置。