# 交易 Web 中文图文用户使用手册

- 2026-10-21 发布 PDF（13 页，含 Playwright 实际截图）：`https://trade.opentradingcore.com/help/OpenTradingCore_Trading_Web_User_Guide_ZH.pdf`
- 对外 Demo 验证：HTTP/2 200、`application/pdf`、2176651 bytes、SHA256 `17705a8bacc35c97f2a91a01e232d391bce240350d7394c8bb90dda9bbe2e609`。PDFKit 确认 13 页，中文可提取。
- 内容：交易入口、注册登录、PC 工作台、切换租户产品、TradingView 图表、盘口与最近成交、限价/市价/条件单、五种持仓/委托/成交/资金记录、个人 API Key、语言偏好、手机端资产和交易操作、常见问题。
- 截图用 Playwright 在当前部署的 Demo 获取，包含专门注册的测试交易员的只读账户与设置界面；没有创建真实 API Key、没有资金或委托操作；不包含密码/Secret。
- 镜像 `local/dc-saas-trade-web:with-zh-guide-20261021` 在既有完整终端镜像上只新增 PDF 文件；Compose 覆盖 `config/trade-web-guide-20261021.yaml`，只重建交易 Web。Core、Order、Trade、MD 未重启。
- 此文档是操作说明，不代表 Trade HA、真实资金和订单一致性验收通过。
