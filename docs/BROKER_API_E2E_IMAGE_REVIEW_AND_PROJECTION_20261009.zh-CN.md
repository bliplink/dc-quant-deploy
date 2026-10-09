# Broker API 实盘式 Demo 验收门禁（2026-10-09）

**状态：代码及镜像门禁已收口；真实 Trader/Broker 交易验收仍未执行，不能报告通过。**

本文件约束 `tests/run-tenant-lifecycle-e2e-host.sh` 调用的 `tests/run-broker-api-e2e-host.sh`。该 Runner 会向隔离测试账户入模拟金、生成订单、请求撤单、取回成交记录，并尝试跨租户操作。当前线上旧版 RobotSvr **仍然不允许执行**此流程；已审查的新 ARM64 测试镜像可通过独立容器执行，无须重启正式 RobotSvr。

## 当前阻断项

`bliplink/com.app.dc.robotsvr` 的 `BrokerApiE2ERunner.java` 已先后通过提交 `77a77be`、`36b80cf` 修复以下两项阻断，最新 GitHub Actions `37928411662` 已通过 Maven 测试及双架构镜像构建：

1. **已修复：** 在发送 `brokerPlace(...)` 前设置清理意图，异常时按本次两个精确 `ClOrdID` 查询及撤销，禁止盲目补单和撤销其他订单。
2. **已修复：** 仅识别明确的后端客户/租户归属拒绝；已对照共享权限模块 `OpenApiAccountAuthority` 确认其实际消息 `location conflicts with authenticated session` 和 `customer account is not available in authenticated tenant`。502、连接超时、Session 失效和内部错误均不算成功，拒绝后还要查询同租户账户证明链路正常。

**门禁方式：** 在读取任何生产/测试凭据和执行 `docker run` **之前**，脚本检查候选镜像的不可变 Docker image ID 是否在 `tests/broker-runner-approved-images.txt`。默认检查线上 RobotSvr（旧版仍阻断）。独立测试指定 `BROKER_E2E_RUNNER_IMAGE_REF=ghcr.io/bliplink/robotsvr:sha-36b80cfca6c70e9c13e1b5f0114b4eb87d0d9872`。浮动 `latest`、`saas-crypto` 标签及上一个不符合实际拒绝文字的 `77a77be` image ID 均拒绝。GHCR ARM64 child manifest `sha256:bb09fc1e98538435a0fe3c4ad7edc8e15a3db3cd64ec2e14342e4343e8ed0038`，远端 config digest `sha256:4ccac4846d00051053e9fb89ae1ca4e0f89f9124b6e16a3045ea3f967428f75e` 已核实。**镜像已使用 `crane` 经本机 10808 代理完整下载并用 `docker load` 导入 Colima**，已验证 tar 与再次 `docker save` 的镜像 config SHA 均为 GHCR 原始 `4ccac...`，12 层 RootFS diff IDs、Entrypoint 等完全一致；Colima `docker image inspect .Id` 报告导入后的 manifest ID `sha256:98c3a2bb1793b06b0c369f00372d18dee54da31363fc9525e268fd6783210a9a`，两个摘要均已按此证据审批。镜像经过 `--network none` 无凭据启动验证，但这不等于真实交易通过。

## 获准执行的条件

1. 已完成：RobotSvr `36b80cf` 修复异常清理、精确跨租户拒绝文字和误报，新增 JUnit 测试。
2. 已完成：GitHub Actions `37928411662` 生成 AMD64/ARM64 GHCR；远端 ARM64 manifest/config digest 已核对；通过本机 10808 代理和 `crane` 完整拉取 ARM64，导入 Colima 并完成镜像内容一致性校验。
3. 已完成：最新 ARM64 config digest 已加入审查清单，上一版 77a77be 已取消批准；执行前仍须本机镜像完整下载且 image ID 匹配，旧版生产容器未批准。
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
