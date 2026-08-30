# DC SaaS 多租户控制面生产验收报告

文档版本：V1.0

验收日期：2026-08-30

生产验证环境：`18.140.45.126`

Compose 项目：`dc-saas`
代码分支：`saas-crypto`

## 1. 验收结论

多租户第一阶段已经完成生产环境端到端验收。系统能够从公开试用申请开始，经平台运营审批自动初始化租户，再由租户用户通过独立 location URL 注册、登录和交易；租户管理员能够管理本租户用户、品种、API Key、流动性 Robot 配置、交易记录、设置和审计。

最终双租户回归使用 `SAASA_E2E_0830160159` 与 `SAASB_E2E_0830160159`。同名用户在两个租户得到不同 user_id，错租户密码、跨租户管理、普通用户审批和交易用户管理访问全部被拒绝。暂停租户后普通用户不能登录，恢复 ACTIVE 后重新开放。

本结论代表控制面已具备产品验收条件，不代表真实资金生产就绪。交易服务跨 location 的请求、Topic、缓存、锁和重放攻击测试仍需继续收口；真实资金上线还需要账本、多源指数、安全合规、高可用和灾备门禁。

## 2. 已交付业务能力

### 2.1 公开申请与平台审批

1. 申请人填写企业/团队、租户代码、联系人、邮箱、预计用户数、试用天数、交易品种和使用场景。
2. 系统返回申请 ID；申请人可用申请 ID 和邮箱查询状态。
3. PLATFORM 运营账号审核申请，普通租户用户没有审批权限。
4. 审批事务初始化 location、试用周期、独立 URL、租户管理员、默认账户、品种和交易配置。
5. 相同请求凭证重复提交不会重复创建租户。

当前独立入口格式：

```text
http://18.140.45.126:18088/#/login?location={LOCATION}
```

### 2.2 租户生命周期

状态覆盖 `TRIAL / ACTIVE / SUSPENDED / EXPIRED`：

- TRIAL/ACTIVE：在注册和交易开关允许时可注册、登录和交易。
- SUSPENDED/EXPIRED：普通用户注册、登录和交易入口被服务端拒绝。
- 恢复 ACTIVE：重新开放登录与交易，历史数据和审计不删除。

### 2.3 租户用户与权限

- 用户名只需在当前 location 内唯一；不同租户允许同名。
- 用户 ID、密码、账户、订单、持仓、资金和管理权限按 location 隔离。
- 租户管理员可以创建、启停本租户用户并重置初始密码。
- 交易用户不能访问租户管理接口；租户管理员不能读取或修改另一 location。
- PLATFORM 审批接口只接受平台运营身份。

### 2.4 租户管理

- 品种：交易状态、价格/数量精度、最小/最大数量、最小名义金额、价格上限、手续费、资金费周期和风险档位。
- API Key：创建、列表和撤销；Secret 只显示一次。
- Robot：租户 API Key、报价档位、价差、数量、库存上限、外部对冲和熔断参数。
- 交易记录：按认证 location 查询订单、成交和交易数据。
- 设置：注册/交易开关、默认语言和品牌参数。
- 审计：用户、品种、API Key、Robot 和设置变更均写入租户审计。

## 3. 服务与数据流

```text
公开申请页
  -> GW -> ManagerSvr -> MySQL(申请)
  -> PLATFORM 审批
  -> MySQL(location/管理员/账户/品种/设置/审计)
  -> 返回 location 独立 URL

租户注册/登录
  -> GW -> LoginSvr
  -> 校验租户状态、注册/交易开关和 location
  -> 创建/读取 location 内用户与会话

租户管理 Web
  -> GW -> AdminSvr
  -> 从认证会话取得权威 location
  -> 用户/品种/API Key/Robot/交易记录/设置/审计
  -> MySQL(所有查询和写入限定 location)

租户交易 Web
  -> GW -> OrderSvr/TradeSvr/MDSvr/LiqSvr
  -> location 独立订单、资金、持仓、强平与订单簿行情
```

GW 当前继续作为通用路由和 Topic 转发层，不硬编码 SaaS。订阅由目标服务 snapshot 校验；校验失败不返回订阅确认，GW 不把 Topic 加入订阅列表。后续可增加可选 SaaS 前置插件，但不能破坏 GW 在非多租户系统中的独立性。

## 4. 自动化测试矩阵

| 场景 | 预期 | 结果 |
|---|---|---|
| 公开提交 A/B 两个申请 | 返回不同申请 ID | PASS |
| PLATFORM 审批 | 创建不同 location、URL 和管理员 | PASS |
| 非 PLATFORM 审批 | 拒绝 | PASS |
| A/B 租户注册同名用户 | user_id 不同 | PASS |
| A 用户使用 B 密码或错误 location | 登录拒绝 | PASS |
| A 管理员读取 B 数据 | 拒绝 | PASS |
| 交易用户访问租户管理 | 拒绝 | PASS |
| 用户创建、启停、密码管理 | 仅本租户生效 | PASS |
| 品种列表与 UPSERT | 规则正确持久化 | PASS |
| 交易记录、设置和审计 | 仅返回本租户 | PASS |
| 暂停 A 租户 | 普通用户登录拒绝 | PASS |
| 恢复 A 租户 | 普通用户重新登录 | PASS |
| 桌面申请/平台/租户管理 | 页面与接口完成 | PASS |
| 390×844 注册/租户管理 | 响应式可操作 | PASS |
| AdminSvr 单元测试 | 13/13 | PASS |
| ManagerSvr 单元测试 | 7/7 | PASS |
| LoginSvr 单元测试 | 5/5 | PASS |
| Trade Web 生产构建 | 构建成功 | PASS |

生产自动化产物：`/data/dc-saas-runtime/e2e-artifacts/tenant-0830160159`。测试租户作为审计证据保留，没有执行数据删除。

最终只读数据库复核结果：

```text
tenant=SAASA_E2E_0830160159,status=ACTIVE,register=1,trade=1
tenant=SAASB_E2E_0830160159,status=TRIAL,register=1,trade=1
shared_users=2,distinct_ids=2
balances=2
symbols=2
audits=7
```

## 5. 真实环境缺陷与修复

1. 历史 `dc_symbol` 数字规则字段存在空字符串，复制到新租户 DECIMAL 列时审批失败。ManagerSvr 和 AdminSvr 已统一用 `TRIM / NULLIF / CAST` 规范化旧数据，并重新完成审批和品种 UPSERT。
2. 部署预检原来把“总内存要求”错误用于“当前可用内存”，运行 SaaS 与量化容器时会阻断安全增量更新。现拆分为总内存至少 7.5 GiB、当前可用内存至少 2 GiB。
3. 浏览器登录成功后路由跳转与响应读取存在自动化竞态。验收脚本改为先捕获登录响应，再断言浏览器会话和目标路由，最终连续通过。
4. 租户表单、暗色表格和移动端标签布局经真实截图复核后完成样式修正，并以不可变公开镜像发布。

## 6. 部署基线

- Trade Web 源码：`97b3afe88928fe0c6b26a8564d88ae5168556dba`
- Trade Web 镜像：`ghcr.io/bliplink/dc-saas-trade-web:source-97b3afe88928fe0c6b26a8564d88ae5168556dba`
- ManagerSvr 租户规则修复：`7e0a7a3bbad8a48bdb7c8dd13a0631efee67f228`
- AdminSvr 租户规则修复：`c2119abbf065506b6fcac2de2f32d05ba3cf2e0c`
- 自动更新只重建镜像发生变化的服务；Web 增量发布没有重启 OrderSvr、TradeSvr、MDSvr 或 LiqSvr。

## 7. 生产截图证据

![公开 SaaS 试用申请](evidence/tenant-application-en.png)

![390×844 租户内注册](evidence/tenant-registration-mobile-en.png)

![平台租户运营与生命周期](evidence/platform-tenant-operations-en.png)

![租户管理员桌面控制台](evidence/tenant-administration-en.png)

![390×844 租户管理员控制台](evidence/tenant-administration-mobile-en.png)

数据库与容器证据见主产品验收文档中的 `evidence/database-evidence.png`；该图和上述图片均采集自生产验证环境，不是设计稿。

## 8. 下一阶段门禁

1. 完成 OrderSvr、TradeSvr、MDSvr、LiqSvr 的跨 location 请求、订阅、缓存、锁、重放和数据库攻击测试。
2. 部署 RobotSvr，验收 APSSvr 行情、租户 API Key 报单、库存风控、熔断和外部反向对冲。
3. 增加自定义域名/证书、套餐配额、2FA、平台/租户 RBAC、导出审批和用量计费。
4. 交易金融正确性继续完成事务 outbox、不可变复式账本、多源指数、完整账户模式和持续对账。
5. 真实资金上线前完成钱包、安全合规、限流、私有流、高可用、PITR、混沌与灾备演练。
