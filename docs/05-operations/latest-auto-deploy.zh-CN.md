# latest 分支自动发布与自动部署

## 1. 目标

将原来的：

- 手工 `commit`
- 手工打 `tag`
- 手工更新 `.env.prod`
- 手工 `pull + restart`

改成更轻量的流程：

1. 代码提交到 `latest` 分支
2. GitHub Actions 自动构建镜像
3. 镜像自动发布 `latest` 与 `sha-<commit>`
4. 服务器定时轮询 `latest`
5. 镜像变化时自动拉取并重启服务

## 2. 适用范围

建议按分批方式启用：

### 第一批

- `web`
- `BatchSvr`
- `INDSvr`
- `SIMSvr`

### 第二批

- `GW`
- `QuantSvr`

说明：

- 越靠近交易执行核心，越不建议一开始就全自动滚动

## 3. GitHub Actions 口径

每个服务的 workflow 建议统一为：

1. `push` 到 `latest` 分支触发
2. 同时发布：
   - `latest`
   - `sha-<commit>`

示例镜像：

- `ghcr.io/bliplink/indsvr:latest`
- `ghcr.io/bliplink/indsvr:sha-7c20c52`

## 4. 服务器侧自动脚本

仓库根目录新增：

- `auto-update-service.sh`

行为：

1. 拉取指定服务镜像
2. 比较拉取前后的本地镜像 ID
3. 若镜像未变化：
   - 不重启
4. 若镜像变化：
   - 调用 `restart-service.sh`
5. 若重启验证失败：
   - 尝试将旧 image ID 重新 tag 回当前镜像引用
   - 再执行一次重启完成回滚

## 5. 用法

### 手工测试

```bash
./auto-update-service.sh indsvr
```

### 预演

```bash
./auto-update-service.sh indsvr --dry-run
```

## 6. 定时任务示例

每 5 分钟检查一次 `indsvr`：

```cron
*/5 * * * * cd /data/strategy/dc-quant-deploy && ./auto-update-service.sh indsvr >> /data/strategy/log/indsvr-auto-update.log 2>&1
```

每 5 分钟检查一次 `web`：

```cron
*/5 * * * * cd /data/strategy/dc-quant-deploy && ./auto-update-service.sh web >> /data/strategy/log/web-auto-update.log 2>&1
```

## 7. 与旧流程的关系

旧流程：

- 手工打 tag
- 手工改 `.env.prod`

新流程：

- 默认走 `latest` 分支自动发布
- `.env.prod` 中对应服务的 TAG 一般保持 `latest`

但仍需保留：

- `sha-<commit>` 级别镜像
- 问题时的人工回滚能力

## 8. 建议

### 建议保留的纪律

1. 核心服务先在非执行侧样板验证
2. 保留 `sha-<commit>` 追溯
3. 每次自动重启后看最近日志
4. 不要所有服务同时一次性切换

### 不建议的做法

1. 直接让所有服务无差别追 `latest`
2. 不做健康检查
3. 不保留回滚路径

## 9. 一句话

`latest` 自动发布的目标是简化发布动作，而不是取消发布纪律。真正合理的做法是：提交到 `latest` 分支自动出镜像，服务器只在镜像变化时拉取并重启，同时保留 `sha-<commit>` 级可追溯与回滚能力。
