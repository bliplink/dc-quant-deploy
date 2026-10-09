# OpenTradingCore 三端 Logo 与管理功能回归验收（2026-10-09）

## 统一标准

唯一主视觉基准：主站 `opentradingcore-web/assets/images/logo-mark.svg`，透明底蓝色渐变六边形，SHA-256：

`a305fff67eaf293e4d74fc13cc6a44964c7c1f1338d2b83fc14c4e9cde6db211`

三个子站使用完全相同的 SVG 字节，不采用 CSS 近似绘制；品牌名称统一为 **OpenTradingCore**。功能区别通过小号标签区分（Tenant Console / Platform Operations），各自原有界面配色和响应式布局保留。四站 favicon.ico 已经为相同的现有图标文件（SHA-256 `1a8108a8e7a5a739af5533bbfc7842df4583e27b1102c1ff803c4f6ff685c46d`），本轮无需更改。

## 源码、发布版本与处理位置

| 系统 | 仓库 / 分支 | 提交 | 正式镜像 Tag | 已统一的品牌位置 |
|---|---|---|---|---|
| 主站 | `opentradingcore-web` | 主站既有资产 | 不重新发布 | 首页顶部及页脚 |
| 交易核心 | `bliplink/dc-trade-web:saas-crypto` | `6620402` | `sha-662040229ea7e6b061969b0b8d6c5228c4380b80` | 交易页面导航、登录、注册 |
| 租户管理 | `bliplink/dc-saas-tenant-web:saas-crypto` | `a9a4fb1` | `sha-a9a4fb1044374b044e5df558147f318d99573f5a` | 登录与申请入口、登录后侧栏 |
| 平台管理 | `bliplink/dc-saas-platform-web:saas-crypto` | `b472c7b` | `sha-b472c7baad2cd1346eef8b752af3820f29caadde` | 登录及登录后侧栏，移除旧 `DC` 字母标记 |

交易端构建基于远端已存在的 5M K 线提交 `420b887`，没有把源码的旧 1H 默认值带回新镜像。此轮三 Web 服务通过各自 GitHub Actions 正式发布，并分别更新到 Mac mini 生产 Demo 的不可变镜像锁：

- 租户 + 平台镜像锁：`dc-quant-deploy@bc1f72f`。
- 交易镜像锁：`dc-quant-deploy@698c6ff`。

仅重建 `tenant-web`、`platform-web` 与 Docker Compose 服务 `web`（Trade Web）；OrderSvr、TradeSvr、RobotSvr、MySQL、Projection 没有因品牌更新重启。

## 实际验收

- 主站 Logo 字节与三端新 SVG 的 SHA-256 完全一致；四站 favicon.ico SHA-256 也一致。
- 交易 Web CI：镜像发布、functional、visual、stress 四套工作流全部 `success`，与整系统 200 租户压力测试不同。
- Chromium 真实浏览器：390px 手机、768px 平板、1366px 桌面；交易导航/登录/注册，租户登录、平台登录，以及两套管理端各自在手机与桌面登录后侧栏，`BRAND_QA_PASS 19/19`。
- 已人工复查 390px 管理登录页及管理端登录后侧栏截图，图标没有遮挡、拉伸、白底或缺失。
- 管理 Web 的登录后 8+3 页面 × 3 尺寸完整回归 `33/33 PASS`。
- 交易 Web 390px 实测 K 线按钮 `5m` 默认选中，1366px 成功加载 K 线 iframe，均无 JavaScript pageerror。
- 三个新 Web 服务镜像均运行，租户/平台 Health 状态为 healthy，Trade Web running，重启次数均为 0。
- 全局健康：12/12 自动 Tape 初始化完成；13 条 Robot 配置中 12 条 RUNNING/40、1 条隔离 QA Robot STOPPED/0；初始化失败 0；Order HA 分区/快照一致；Projection orphan mutation 0，Trade/Order watermark mismatch 0。
- 公网复核：主站、交易、租户三站 HTTPS 返回 200；平台站首次连接瞬时失败后，重新测试连续 3 次 HTTPS 200（TLS 校验通过），本地 18090 同时返回 200；Cloudflare Tunnel 进程保持运行。记录瞬时网络异常，但未复现持续故障。

### 复跑方法

本地 Mac mini 已预置 `dc-saas-web-e2e-runner`。先在当前会话加载私有部署环境（不得提交、打印、分享密钥）：

```bash
MANAGEMENT_QA_SCRIPT=brand-unification-web-qa.js python3 tests/run-management-mobile-qa.py
QA_ONLY_UI=1 python3 tests/run-management-mobile-qa.py
ENV_FILE=/Users/kong/.opentradingcore/dc-saas-fresh2-20261005.env bash tests/check-projection-consistency-host.sh
bash tests/verify-order-cluster-state-host.sh
```

屏幕截图和 JSON 报告在 E2E runner 的 `/artifacts/brand-unification-qa/`（Mac mini 的 `~/.opentradingcore/dc-saas-runtime-fresh2-20261005/e2e-artifacts/brand-unification-qa/` 映射目录）。

## 未执行/保持限制

- 平台管理员实际执行 `APPROVE` 手工开通新租户未通过本轮完整 E2E；此前此步骤遇安全检查拦截，本轮未尝试绕过。
- 按用户要求，**不进行现有租户服务路由修改、路由回滚或集群 Placement 发布**。
- 200 租户持续压测、实际业务订单 TPS/P95/P99 延迟、真实故障注入仍属于独立待办；不能拿本次 Trade Web UI CI 的 stress job 当作后端系统容量验收。
