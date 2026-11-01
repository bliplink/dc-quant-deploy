# T393｜MD 最新成交价与最近成交第一条不一致、iPhone 13 时间缺失（2026-11-01）

## 真实复现
同一 Mac Demo，Playwright iPhone 13 390×844，租户 NWQYBB，BTCUSDT：

| 数据 | 正式 18088（T391） | T393 候选 18190 |
|---|---:|---:|
| MD 统计 LastPrice | 77960.0 | 77960.0 |
| 盘口中间价 | 77866.4 | 77960.0 |
| 最近成交第一条 | 77866.4 | 77960.0 |
| 最近成交时间 | 空 | ~14:25:47 |
| 最近成交记录 | 200 | 200 |

测试候选三次静态读取均显示 LastPrice/中间价/最近成交首行=77960.0，时间 ~14:24:53。尚未验证不断变化的成交流下的长期严格同步。~ 表示当地接收时刻，非权威成交时间。

## 原因与修复
- 正式 Trade Web 运行 T391（main_2026_11_01_13_57_58.js）；T392 时间与移动端列宽修复此前仅上线候选端口 18189，未部署正式 18088，因此用户仍看到时间空白。
- MD TraderFacade 按执行追加 NoMDEntries，同时汇总 LastPrice。Web 的 recentTradeHandler 混合实时 ticker 与 recent trade snapshot、AdminSvr 历史，再按时间排序；成交时间缺失或晚到历史可能使首行脱离权威 MD LastPrice。
- 新增 recentTradeRecencyUtils.js，从 MD 同租户 ticker 的真实 NoMDEntries 中倒序匹配 LastPrice 对应成交（拒绝凭 LastPrice 伪造执行），将真实对应执行保留在最近成交列表首位；历史加载不能覆盖。
- Header.jsx 校验租户 Location，清理跨租户缓存；ticker 的 pubTrade 传入权威标志，最近成交历史仍走非权威通道。
- T392 已修移动端时间显示：缺少 MDEntryTime 时显示带 ~ 的接收时间，并把狭窄盘口时间列调整为可显示完整 HH:mm:ss。
- 后续补了 pinned 执行在 200 条可见历史之外的保护；最终版已重新完成 13/13 Mocha PASS、Webpack 生产构建 PASS，并生成 local/otc-t393-web:md-recent-consistency-final 镜像。

## 已通过与未通过
- 首版 T393 pure helpers + history/ticker/orderbook 的 Mocha **12/12 PASS**，生产 build-prod PASS，镜像 local/otc-t393-web:md-recent-consistency 已在候选端口 18190 运行 /healthz PASS。
- 候选页面 iPhone 13 Playwright 样本上述价格一致、时间可见。
- 最后新增 >200 行 pin 保留保护及 1 个新单测后，13/13 单测 PASS、最终构建 PASS，镜像 local/otc-t393-web:md-recent-consistency-final 在独立端口 18191 运行。Playwright iPhone 13 (390x844) 5/5 组采样中 LastPrice、盘口中间价、最近成交首行均为 78025.5；时间列宽 67px，~15:54:16 等时间可见。采样期间无成交价变化，不构成持续动态交易严格一致性证明。
- 正式 18088 T391 → T393 容器切换命令被执行环境安全检查拦截，没有执行。原 Web 与 Order/Trade 仍运行。
- 权威实际成交时间仍需从 Order/Trade→MD 的 TransactTime/MDEntryTime 链路复核；目前 ~ 是近似接收时间，不可当做真实执行时间。

## 继续执行
1. 使用受支持的发布路径完成最终变更 Mocha/production build，并在 iPhone 13 长时间真实连续成交场景验证最新价、首行价格及时间。
2. 原 Web 容器保持 18088 服务，首版候选在 18190、最终版镜像在 18191；取得允许的容器发布权限后再滚动替换 T393，并验证公网域名与 iPhone Safari。WebKit 自动化尝试因本机缺少 Playwright WebKit 浏览器二进制未能完成，不视为真机验收。
3. 保留旧镜像与容器回退，Order/Trade 只有 Common 集群启动接线和真实 E2E 满足门禁后再切换；不使用 GitHub Actions。
