# APSSvr 每日定时重启

生产机 `18.140.45.126` 使用 UTC。APSSvr 按北京时间每天 01:00 重启，
因此 `ec2-user` 的 crontab 使用 UTC 17:00：

```cron
# BEGIN DC APSSVR DAILY RESTART
# 01:00 Asia/Shanghai = 17:00 UTC (server timezone: UTC)
0 17 * * * cd /home/ec2-user/dc-quant-deploy && PATH=/usr/local/bin:/usr/bin:/bin /usr/bin/flock -n /tmp/dc-apssvr-restart.lock /usr/bin/bash ./restart-service.sh apssvr >> /home/ec2-user/dc-quant-deploy/logs/apssvr-cron-restart.log 2>&1
# END DC APSSVR DAILY RESTART
```

约束与行为：

- 必须调用仓库中的 `restart-service.sh apssvr`，不在 cron 中复制 Docker 命令。
- `flock` 防止上一次重启未结束时重复执行。
- `restart-service.sh` 在普通用户不能访问 Docker socket 时会自动执行免交互 `sudo`。
- 重启输出写入 `logs/apssvr-cron-restart.log`，不得把密钥或口令写入 crontab。
- 服务器时区若从 UTC 调整为其他时区，必须同步校正 cron 表达式。

检查命令：

```bash
crontab -l
systemctl is-active crond
cd /home/ec2-user/dc-quant-deploy
./restart-service.sh apssvr --dry-run
sudo -n docker ps --filter name=dc-apssvr
tail -100 logs/apssvr-cron-restart.log
```

首次配置于 2026-10-13；当时 `crond=active`、脚本 dry-run 通过、
`sudo -n` 和 APSSvr 容器查询通过。下一次计划执行时间为
2026-10-14 01:00（Asia/Shanghai）。
