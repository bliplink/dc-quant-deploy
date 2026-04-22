# QuantSvr 风控规则与 Telegram 使用说明

`QuantSvr` 是实盘运行服务，负责加载 live 策略、消费信号、执行下单、维护运行状态、发送 Telegram 消息和生成日末复盘。本文面向部署后的使用者，说明运行时风控规则和 Telegram 入口怎么用。

## 1. QuantSvr 在实盘链路中的位置

```text
strategy_live_registry -> QuantSvr -> TeleStrategy -> signal -> order -> trade -> position
```

内部生成策略和外部 `pubSignal` 信号最终都会进入 `TeleStrategy`。策略是否真正开仓，不只取决于信号本身，还会经过运行状态、时间窗口、仓位、亏损、滑点、止损止盈等风控检查。

## 2. 策略运行状态

`TeleStrategy` 按品种维护运行状态，常见状态如下：

| 状态 | 含义 |
| --- | --- |
| `ACTIVE` | 正常运行，可以处理新开仓信号。 |
| `WARN` | 风险预警，通常由滑点等异常触发。 |
| `STOP_NEW` | 暂停开仓，已有持仓和后续平仓逻辑仍需继续关注。 |
| `HALT` | 强制停用，通常表示更严重的执行风险。 |
| `REVIEW_REQUIRED` | 需要复盘后再决定是否继续。 |

如果某个品种存在 `riskPauseReason`，开仓前检查会拒绝新开仓，并在运行信息里展示暂停原因。

## 3. 开仓前风控

每个新开仓信号会先经过以下检查：

- 杠杆检查：实际杠杆超过系统上限时，拒绝开仓并提示追加保证金或降低风险。
- 时间窗口：只在 `beginRunTime` 到 `endRunTime` 内允许新开仓。
- 仓位数量：`checkMaxPositionCount` 控制最大持仓数量。
- 持仓金额：`checkMaxPositionValue` 控制账户当前持仓和挂单合计后的最大风险暴露。
- 多空比例：`checkMaxPositionSide` 控制多头和空头持仓数量比例，避免方向过度集中。
- 单笔金额：`symbolValue` 控制单次信号计划投入金额。
- 品种状态：该品种如果已经被风控暂停，新开仓会直接被拒绝。

这些规则通过 Telegram 策略参数菜单可查看和调整，适合部署方按账户规模设置更保守的默认值。

## 4. 当日波动与持仓时间控制

`check1DBP` 用于控制当日涨跌幅风险。当某个品种日内涨跌幅绝对值达到阈值，且当前持仓处于亏损或没有有效持仓保护时，策略会暂停该品种开仓到下一日。

`checkMaxPositionTime` 用于控制最长持仓时间。持仓时间超过阈值后，系统会尝试执行平仓逻辑，避免仓位长时间失控。

## 5. 止损止盈规则

信号可以携带：

- `stopPrice`：动态止损价。
- `takerPrice`：动态止盈价。

如果信号提供了这两个价格，`TeleStrategy` 会优先使用信号价格，而不是回退到策略默认百分比。

执行逻辑：

- 多头持仓：当前价小于等于 `stopPrice` 视为触发止损，当前价大于等于 `takerPrice` 视为触发止盈。
- 空头持仓：当前价大于等于 `stopPrice` 视为触发止损，当前价小于等于 `takerPrice` 视为触发止盈。
- 开仓成交后，系统会尝试挂出条件止损和条件止盈单。
- 条件止损单使用 `STOP_MARKET`，条件止盈单使用 `TAKE_PROFIT_MARKET`。

如果没有信号级止损止盈，系统才会使用策略参数中的 `stopLossPrice1`、`takeProfitPrice1` 等默认比例计算保护单。

## 6. 订单类型与挂单有效期

外部 `pubSignal` 可指定：

- `type = LIMIT` 或 `MARKET`
- `validUntilTime`

当前默认值：

- 订单类型默认 `LIMIT`。
- `validUntilTime` 未传时，默认使用当前时间后 30 分钟。

建议第三方调用方：

- 想控制成交价时使用 `LIMIT`。
- 想尽快成交时使用 `MARKET`，但要自行承担滑点风险。
- 对短时信号明确传入 `validUntilTime`，避免过期行情继续挂单。

## 7. 亏损与滑点风控

`TeleStrategy` 会根据成交回报更新品种级风险状态：

- 连续亏损：`maxConsecutiveLoss` 达到阈值后，该品种暂停开仓到下一日。
- 当日亏损：`maxDailyLoss` 达到阈值后，该品种暂停开仓到下一日。
- 止损滑点：如果止损成交价相对信号止损价出现严重不利滑点，会进入风险预警或暂停开仓。
- 极端滑点：如果滑点达到灾难级别，会进入 `HALT`，需要人工复盘。

滑点判断会结合最近历史样本。样本不足时，系统使用保守 fallback 阈值；样本充足后，会参考中位数和 P90 动态判断滑点是否异常。

## 8. 自动订阅品种

外部信号默认 `autoSubscribeSymbol = true`。当运行中的策略收到外部信号，且还没有订阅该 `symbol` 时，系统会自动把该品种加入订阅，让后续处理接近 Telegram 手动选择品种后的流程。

内部策略信号默认不自动订阅，避免内部生成信号意外改变用户当前订阅范围。

## 9. Telegram 基础配置

Telegram 能力由 `QuantSvr` 复用同一套 Bot 配置：

- `enableBot`：是否启用 Telegram bot。
- `botGroupId`：群消息目标群。
- `adminList`：管理员列表。
- `strategyBot`：策略 Bot handler，默认使用 `TeleBotImplHandler`。

真实 bot token、群号和管理员信息属于敏感配置，不应提交到开源仓库。

## 10. Telegram 用户操作

用户进入 Telegram bot 后，先发送：

```text
/start
```

常用菜单：

- 设置 API 账号：绑定交易账户 API。
- 设置策略参数：配置策略模式、交易品种、仓位、杠杆、止盈止损、运行时间、风控阈值等。
- 查看策略参数：查看当前参数、运行状态、暂停原因、连续亏损次数等。
- 启动策略：启动当前用户策略。
- 停止策略：停止当前用户策略。
- 策略运行情况：查看当前运行状态。

常用命令：

- `/report`：查看复盘或报告入口。
- `/hotlist`：查看热榜相关信息。
- `/cancelall`：撤销当前相关挂单。
- `/deleteapi`：删除当前绑定 API。

管理员命令：

- `/count`
- `/queryTeleUser`
- `/queryLicense`
- `/updateLicense`

管理员命令建议只对可信用户开放。

## 11. Telegram 群消息

系统会向 `botGroupId` 对应群发送几类消息：

- 交易播报：开仓、平仓、盈亏等运行消息。
- 外部信号审计：`pubSignal` 成功接收后发送中文极简提示。
- 自动订阅提示：外部信号触发自动订阅时提示新增品种。
- 手工群消息：通过 MCP `sendMsg` 发送调用方自定义文本。

`sendMsg` 只接收一个字段：

```json
{
  "payload": {
    "message": "最新交易播报\n策略：xl\n品种：BTCUSDT\n方向：多头开仓"
  }
}
```

该接口不开放群号，固定发送到 `QuantService.botGroupId`。

## 12. 外部信号 Telegram 审计

`pubSignal` 成功写入并提交广播后，会异步发送中文审计消息。消息只包含核心字段：

- 策略
- 品种
- 方向
- 信号价格
- 止损价格
- 止盈价格
- 接收时间

审计消息不包含 `id`、`text`、`scene`、`strategyPayload` 等内部字段，避免第三方群里信息过载。

方向中文映射：

| side | ocType | 中文含义 |
| --- | --- | --- |
| `BUY` | `OPEN` | 多头开仓 |
| `SELL` | `OPEN` | 空头开仓 |
| `BUY` | `CLOSE` | 空头平仓 |
| `SELL` | `CLOSE` | 多头平仓 |

## 13. 常见问题

### 信号写入成功但没有下单

优先检查：

- 策略是否启动。
- `symbol` 是否已订阅，或外部信号是否允许 `autoSubscribeSymbol`。
- 信号周期 `text` 是否匹配策略订阅。
- 当前品种是否处于 `STOP_NEW`、`HALT` 或存在 `riskPauseReason`。
- 是否超过最大持仓数量、最大持仓金额、运行时间窗口、当日亏损或连续亏损阈值。
- `type` 是否符合 `LIMIT` / `MARKET`。
- `validUntilTime` 是否已经过期。

### Telegram 中文乱码

优先确保：

- 文档、配置文件、请求体都使用 UTF-8。
- MCP 调用发送 JSON 时显式使用 UTF-8。
- 不要用本地控制台默认编码判断文件是否乱码，Windows PowerShell 直接打印 UTF-8 中文时可能显示异常。

### 群里没有收到消息

优先检查：

- `enableBot` 是否开启。
- `botGroupId` 是否配置正确。
- Bot 是否已经加入目标群。
- Telegram token 是否有效。
- `QuantSvr` 日志中是否有 Telegram API 报错。
