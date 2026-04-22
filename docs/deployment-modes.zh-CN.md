# 部署模式

## 1. 从无到有部署

```bash
./deploy-standalone.sh
```

## 2. 已有 ClickHouse 后部署

```bash
cp .env.external-clickhouse.example .env.prod
mkdir -p control.prod
cp control.prod.example/ATSConfig.ini control.prod/
cp control.prod.example/DBPoolConfig.ini control.prod/
cp control.prod.example/jaas.ini control.prod/
cp -a control.prod.example/overrides control.prod/
vi .env.prod
vi control.prod/ATSConfig.ini
vi control.prod/DBPoolConfig.ini
vi control.prod/jaas.ini
./deploy-with-external-clickhouse.sh
```

## 3. 手动初始化已有 ClickHouse

```bash
./clickhouse/apply-init.sh
```
