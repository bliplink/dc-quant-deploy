# Broker API 实盘式 Demo 验收门禁（2026-10-09）

**状态：代码及镜像门禁已收口；真实 Trader/Broker 交易验收仍未执行，不能报告通过。**

本文件约束 `tests/run-tenant-lifecycle-e2e-host.sh` 调用的 `tests/run-broker-api-e2e-host.sh`。该 Runner 会向隔离测试账户入模拟金、生成订单、请求撤单、取回成交记录，并尝试跨租户操作。当前线上旧版 RobotSvr **仍然不允许执行**此流程；已审查的新 ARM64 测试镜像可通过独立容器执行，无须重启正式 RobotSvr。

## 当前阻断项

此前 `bliplink/com.app.dc.robotsvr` 的 `src/main/java/com/app/dc/robot/BrokerApiE2ERunner.java` 曾有两项阻断，已在提交 `77a77bec8bea0cb02cdb9276b7a60462fbe1a89b` 修复并通过 GitHub Actions `37927294455`：

1. 目前 `makerResting=true` 在 `brokerPlace(...)` **返回之后**才设置：网关受理订单但响应丢失时可能跳过异常清理。应将清理意图在发送前注册，并在异常后按 `ClOrdID` 查询/撤销。不可在不知道订单是否接受时盲目补单。
2. 当前 `catch (Exception expected) { rejected=true; }` 将连接失败、超时、内部错误视为“跨租户鉴权正确拒绝”。必须解析明确的服务端身份/客户归属拒绝码，并补测本租户正向请求依旧成功。

**门禁方式：** 在读取任何生产/测试凭据和执行 `docker run` **之前**，验收脚本读取镜像的不可变 Docker image ID（`sha256:...`）并与 `tests/broker-runner-approved-images.txt` 匹配。默认检查线上当前运行的 RobotSvr（旧版仍阻断）。可以通过 `BROKER_E2E_RUNNER_IMAGE_REF=ghcr.io/bliplink/robotsvr:sha-77a77bec8bea0cb02cdb9276b7a60462fbe1a89b` 指向已拉取到本机的独立镜像；浮动 `latest`、`saas-crypto` 标签及未经审查的 image ID 一律拒绝。2026-10-09 已审核 ARM64 的 config image ID：`sha256:24bb08e1ac73783f87e8c1ac32391004e5bfe4661b9ecc6b72ef2912c45f81fc`。这只是**允许隔离验收的镜像**，不是已经通过真实交易。

## 获准执行的条件

1. 已完成：RobotSvr 的 `saas-crypto` 提交 `77a77be` 修复异常清理与跨租户错误分类，新增 JUnit 测试，CI 成功。
2. 已完成：GitHub Actions `37927294455` 生成 AMD64/ARM64 GHCR，ARM64 镜像已拉取并核对 SHA。
3. 已完成：经代码/CI/镜像核对，ARM64 不可变 image ID 已加入审查清单；未批准旧版生产容器。
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
