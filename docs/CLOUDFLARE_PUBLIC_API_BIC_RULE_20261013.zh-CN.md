# 交易公开 API：Cloudflare Python 客户端兼容规则

**适用域名**：`trade.opentradingcore.com`。仅针对 `POST /api`（签名登录）和 `POST /httpapi/`（业务网关）。不修改 Gateway 透传逻辑；不允许任何未认证请求通过业务鉴权。

## 2026-10-13 实测

同样的匿名公开交易对查询，`curl/8.4.0` 与 `OpenTradingCore/1.0` 均 HTTP 200，`Python-urllib/3.9` 收到 Cloudflare HTTP 403 / Error 1010；本地 Gateway 对合法公开查询可正常响应。该结果证明问题发生在 Cloudflare 边缘，而非 AdminSvr 的业务查询权限。

## 最小范围规则（需要 Cloudflare Zone 管理员发布）

在 Cloudflare **Security → WAF → Custom rules** 新建规则：

```text
(http.host eq "trade.opentradingcore.com"
 and http.request.method eq "POST"
 and http.request.uri.path in {"/api" "/httpapi" "/httpapi/"})
```

选择 **Skip**，在 **Products** 中**只勾选 Browser Integrity Check**（API `products: ["bic"]`）；不要勾选跳过其他 WAF、自定义规则、限速或 Super Bot Fight Mode。启用请求匹配日志。若上线后仍出现 403，请先按 Cloudflare Security Events 的 Ray ID 查明是否为 User Agent Blocking 或其他规则，再针对性处理，**不要扩大到整站跳过所有 WAF**。

外网验收（不涉及 API Key）：

```bash
python3 tests/cloudflare-api-client-probe.py --proxy http://127.0.0.1:10808 --expect-open
```

该脚本只调用公开行情符号查询，分别模拟普通 Python 和 API 客户端的 User-Agent；不会下单或读取私有账户。

参考：
- https://developers.cloudflare.com/waf/tools/browser-integrity-check/
- https://developers.cloudflare.com/waf/custom-rules/skip/options/
- https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-1xxx-errors/error-1010/

**发布状态**：规则尚未发布到 Cloudflare Zone。此文件只是管理员操作及验收说明，不应据此认定问题已修复。
