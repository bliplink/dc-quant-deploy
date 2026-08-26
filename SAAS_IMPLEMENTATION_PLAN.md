# DC 加密货币 SaaS 实施方案

## 1. 产品与分支边界

- SaaS 与量化是两套独立系统；所有 SaaS 仓库固定使用 `saas-crypto` 分支。
- SaaS 部署不包含、不启动 QuantSvr、INDSvr、CustomIndSvr、SIMSvr、BatchSvr，也不使用量化 Web。
- 可复用 `common`、GW、MD、APS、Order 等代码能力，但运行配置、容器、端口、数据目录和发布标签完全隔离。
- 多租户唯一键为 `location`，不再增加 `tenant_id` 或另一套平行租户概念。
- MySQL 保存用户、会话、订单、成交、资金、持仓和配置；ClickHouse 只保存行情和 K 线。

## 2. 目标服务拓扑

| 领域 | 服务 | 主要职责 | 数据库 |
| --- | --- | --- | --- |
| 接入 | dc-trade-web、GW、LoginSvr | 登录、鉴权、WebSocket/HTTP 接入、租户上下文 | MySQL |
| 行情 | APSSvr、MDSvr | 外部行情、订单簿、逐笔、K 线 | ClickHouse |
| 交易 | OrderSvr、TradeSvr、LiqSvr | 撮合、资金/持仓、风险与强平 | MySQL |
| 管理 | ManagerSvr、AdminSvr | 用户、权限、产品、运营查询 | MySQL |
| 发现 | ZooKeeper | 独立服务发现 | 专用数据目录 |

部署基线为 13 个容器，Compose 项目、容器名和运行目录均以 `dc-saas` 命名。

## 3. `location` 多租户规则

### 3.1 信任边界

1. LoginSvr 登录成功后，将 `location` 与用户身份绑定到服务端会话。
2. GW 从已认证会话注入租户上下文；业务接口不得只信任客户端报文中的 `location`。
3. 客户端显式传入 `location` 时，必须与会话租户一致，否则拒绝请求并记录审计日志。
4. GW 到各服务、服务间消息、Topic、内存缓存键、幂等键和数据库条件必须继续携带同一个 `location`。
5. 后台跨租户查询必须使用单独的管理员权限和显式租户范围，不能复用普通用户接口绕过隔离。

### 3.2 数据约束

现有表虽然已有 `location` 字段，但多个字段允许 NULL，且主要主键/唯一键没有包含 `location`。改造必须通过版本化迁移完成，不能直接覆盖生产表。

| 表/数据 | 当前主要风险 | 目标约束或索引 |
| --- | --- | --- |
| `dc_users` | `user_name` 全局唯一，`location` 可空 | `location NOT NULL`；唯一键 `(location,user_name)`；用户 ID 方案明确后增加对应组合唯一键 |
| `dc_users_balance`、`dc_users_config` | 主键只有 `user_id` | 主键/唯一键包含 `(location,user_id)` |
| `dc_users_symbol_config` | 主键缺少租户 | `(location,user_id,security_id)` |
| `dc_orders` | 主键和查询索引缺少租户 | `(location,order_id,user_id)` 及以 `location` 开头的活动订单索引 |
| `dc_orders_execorders` | 成交主键和索引缺少租户 | `(location,exec_id,user_id)` 及租户化历史查询索引 |
| `dc_orders_position` | 同用户同产品会跨租户冲突 | `(location,user_id,security_id)` |
| 日结、现金流水、Posting、Session | 查询和索引并非全部租户化 | 所有租户数据索引以 `location` 为首列或包含强制租户条件 |
| ClickHouse K 线 | 历史结构缺少租户维度 | 写入、排序键和查询均包含 `location` |

迁移顺序：数据盘点与回填 -> 双读校验 -> 增加非空约束和新索引 -> 切换全部查询 -> 删除旧约束。每一步都要有回滚 SQL 和两租户隔离回归测试。

### 3.3 代码审计重点

- ManagerSvr/AdminSvr 仍有按 `user_id`、`user_name` 或全表查询而未限定 `location` 的 SQL，必须逐条分类为“平台公共数据”或“租户数据”。
- TradeSvr 等服务的部分内存键使用字符串直接拼接，例如 `userID + location`；统一改为无歧义复合键对象或带长度/分隔符的规范编码。
- 空字符串和 NULL 不得作为正式租户；仅在一次性数据迁移期间允许映射到明确的兼容租户。
- 所有 DAO 改造均增加同 `user_id`、同 `security_id`、不同 `location` 的正反向测试，确保读、写、更新、删除均不串租户。

## 4. 交易能力实施阶段

### 阶段 A：可部署基线

- 完成独立 Docker Compose、配置生成、安装、校验、卸载与保留/清除数据流程。
- 在 64 环境完成首次部署、两租户冒烟、卸载清除、再次部署回归。
- 冻结一套基线镜像和数据库快照，记录所有服务健康状态与关键日志。

### 阶段 B：租户强隔离

- 完成会话租户注入、跨层传播、DAO 审计、组合键迁移和缓存键改造。
- 自动化覆盖登录、行情订阅、下单、撤单、成交、余额、持仓、资金流水、强平和后台查询。
- 在应用、数据库和消息 Topic 三层分别验证跨租户访问失败。

### 阶段 C：Binance/Bybit 类交易语义

- 建立共享产品规则：价格精度、数量步长、最小名义价值、价格保护和交易状态。
- 完成 Market、Limit、Stop/StopMarket、TakeProfit、PostOnly、IOC、FOK、GTC、ReduceOnly。
- 完成单向/双向持仓、逐仓/全仓、杠杆、保证金、手续费、资金费率和标记价格。
- API 错误码、订单状态机、WebSocket 增量序列和重连补偿必须由契约测试固定。

### 阶段 D：资金安全与风险

- 引入不可变账本分录，保证余额变化可追溯且借贷恒等；业务余额由账本校验或派生。
- 所有下单、撤单、成交、充值、提现和外部回报使用幂等键。
- 增加对账任务、异常补偿、风险限额、强平阶梯、ADL 和保险基金规则。
- 在真实资金接入前完成并发、故障注入、重复消息、乱序消息和恢复演练。

### 阶段 E：生产化

- API Key/Secret 进入密钥系统并加密存储，不写入 Git、镜像或普通日志。
- 增加租户级限流、审计、指标、链路追踪、告警、备份和恢复演练。
- 使用不可变 `sha-*` 镜像从 QA 晋级到 Staging/Production；禁止引用量化 `latest` 标签。
- 建立滚动升级、数据库向前兼容和一键回滚流程。

## 5. 每阶段验收门槛

1. 构建：所有仓库 tracked working tree 干净，单测及镜像构建通过。
2. 部署：13 个 SaaS 容器健康，旧 `/opt/sumscope` 进程和端口不变。
3. 隔离：两个 `location` 可使用相同用户/产品标识，查询和事件互不可见。
4. 交易：订单状态转换唯一合法，资金/持仓/成交/手续费可对账。
5. 故障：服务重启、消息重复和数据库短暂中断后无重复成交或资金漂移。
6. 卸载：默认保留数据；`--purge-data` 只删除 `/opt/dc-saas-runtime` 和专用构建缓存。

## 6. 推荐提交与发布节奏

- 每个仓库只提交该服务内可独立验证的小改动，及时推送 `saas-crypto`。
- 数据库迁移与兼容代码先提交，约束收紧在数据校验完成后单独提交。
- 部署仓库记录各服务精确镜像 digest/commit，不用跨系统的移动标签。
- 每一阶段完成后保留测试报告、迁移校验结果、部署清单和回滚点。
