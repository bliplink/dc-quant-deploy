# Broker API 实盘式 Demo 验收门禁（2026-10-09）

**状态：BLOCKED — 不得将此状态报告为真实 Broker/Trader API 闭环已通过。**

本文件约束 `tests/run-tenant-lifecycle-e2e-host.sh` 调用的 `tests/run-broker-api-e2e-host.sh`。该 Runner 会向隔离测试账户入模拟金、生成订单、请求撤单、取回成交记录，并尝试跨租户操作。当前线上 RobotSvr **不应被批准执行**这个副作用较大的验收流程。

## 当前阻断项

`bliplink/com.app.dc.robotsvr` 的 `src/main/java/com/app/dc/robot/BrokerApiE2ERunner.java` 至少还有两项需要修复并验证：

1. 目前 `makerResting=true` 在 `brokerPlace(...)` **返回之后**才设置：网关受理订单但响应丢失时可能跳过异常清理。应将清理意图在发送前注册，并在异常后按 `ClOrdID` 查询/撤销。不可在不知道订单是否接受时盲目补单。
2. 当前 `catch (Exception expected) { rejected=true; }` 将连接失败、超时、内部错误视为“跨租户鉴权正确拒绝”。必须解析明确的服务端身份/客户归属拒绝码，并补测本租户正向请求依旧成功。

**门禁方式：** 在读取任何生产/测试凭据和执行 `docker run` **之前**，宿主验收脚本检查 `dc-saas-robotsvr` 当前容器的 **不可变 Docker image ID**（`sha256:...`）。只有此摘要出现在提交审查过的 `tests/broker-runner-approved-images.txt` 才能运行。当前清单**故意为空**；不能因希望跑通测试就批准已知不安全的镜像，也不能使用浮动 `latest` 替代 digest。该门禁不改变正在工作的 RobotSvr 容器。

## 获准执行的条件

1. 在 RobotSvr 的 `saas-crypto` 分支修复 Java Runner，补充 mock 级异常重试/残单清理和跨租户错误码回归，代码提交并通过 CI。
2. GitHub Actions 完成 AMD64/ARM64 GHCR 镜像构建。审核具体代码 SHA 与正式镜像的不可变 image ID 一致。
3. 由审核者将**明确验证过**的 `sha256:...` 添加到 `tests/broker-runner-approved-images.txt` 并提交，不要批准上一个已知不安全版本。
4. 仅使用本次新建、隔离且可清理的模拟租户。不得读取或输出正式租户 Secret、Session、密码，不操作既有 Robot 策略/密钥。
5. 验收 Broker/Trader 签名登录、个人/代客交易权限、客户归属隔离、入出金和成交，按权威数据库与 `ClOrdID` / `ExecID` 核对，最后验证撤销 Key 后不能再登录。
6. 全程保留可追溯的 Git commit、镜像 digest、时间、租户（脱敏）、业务响应状态与数据库核对结果；**不能以离线 mock 或页面 HTTP 200 替代真实交易证据**。

## Projection 最终一致性

`tests/run-broker-api-e2e-host.sh` 中的数据库核对为**只读**，最多等待 45 秒：

- 全部 5 项为精确一次入金/出金和指定 `ExecID` 成交：PASS。
- 仅有 0/1，部分数据尚未持久化：WAIT，直到超时。
- 任意计数 >1、非数值、行数错误：立即 FAIL，禁止误报。

这段等待用于吸收 Projection 的异步落库时间，不会制造测试委托，不会补单或自动修复交易数据。

## 离线回归

```sh
bash -n tests/run-broker-api-e2e-host.sh
python3 -m unittest discover -s tests -p 'test_broker_runner_review.py' -v
python3 -m unittest discover -s tests -p 'test_broker_db_evidence.py' -v
python3 -m unittest discover -s tests -p 'test_broker_evidence_contract.py' -v
```

这些测试在 GitHub Actions `Validate API acceptance harness` 中执行，**无需生产环境连接和凭据**。
