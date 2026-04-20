# 发布流程

## 标准规则

正式发布使用镜像 tag。

不要把“往服务器上传单个 jar”当成这个仓库的标准发布路径。

## 正常发布路径

1. 修改应用源码
2. 从对应源码仓库发布新的镜像 tag
3. 更新 `.env.prod` 里的对应 tag
4. 执行 `./validate.sh`
5. 执行 `./deploy.sh`

## 镜像归属

- `zookeeper` 来自 `bliplink/zookeeper`
- `gateway` 来自 `bliplink/gateway`
- `mdsvr` 来自 `bliplink/com.app.dc.mdsvr`
- `apssvr` 来自 `bliplink/com.app.dc.apssvr`
- `quantsvr` 来自 `bliplink/com.app.dc.quantsvr`
- `indsvr` 来自 `bliplink/com.app.dc.indsvr`
- `simsvr` 来自 `SKT-Walter/com.app.dc.simulation`
- `batchsvr` 来自 `bliplink/com.app.dc.batchsvr`
- `web` 来自 `SKT-Walter/com.app.dc.web`

## 应急规则

如果某次临时排障必须手工覆盖 jar，应将其视为一次性偏离标准流程。

原因很简单：容器下次重启后，仍然会回到镜像内版本。

## 回滚规则

回滚依赖镜像版本和控制文件备份：

1. 停掉当前 Compose 栈
2. 恢复之前备份的 `control`
3. 如果旧启动器还存在，则重启旧进程

回滚不会删除 ClickHouse 数据。
