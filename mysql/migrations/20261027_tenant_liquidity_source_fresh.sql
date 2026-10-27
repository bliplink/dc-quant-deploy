-- 2026-10-27 Fresh Demo schema catch-up.
-- ManagerSvr RobotRuntimeService requires tenant system-liquidity gating.
-- Fresh initialization must produce the same columns as upgraded demos.
-- No tenant rows or historical state is modified here.
SET @db='dc';
SET @table='dc_tenant';
SET @sql = (
  SELECT IF(COUNT(*)=0,
    'ALTER TABLE dc.dc_tenant ADD COLUMN liquidity_source VARCHAR(16) NOT NULL DEFAULT ''SYSTEM'' COMMENT ''SYSTEM or BROKER''',
    'SELECT ''liquidity_source already exists''')
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA=@db AND TABLE_NAME=@table AND COLUMN_NAME='liquidity_source'
);
PREPARE t171_liquidity_stmt FROM @sql;
EXECUTE t171_liquidity_stmt;
DEALLOCATE PREPARE t171_liquidity_stmt;
SET @sql = (
  SELECT IF(COUNT(*)=0,
    'ALTER TABLE dc.dc_tenant ADD COLUMN source_switch_state VARCHAR(16) NOT NULL DEFAULT ''ACTIVE'' COMMENT ''ACTIVE or SWITCHING''',
    'SELECT ''source_switch_state already exists''')
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA=@db AND TABLE_NAME=@table AND COLUMN_NAME='source_switch_state'
);
PREPARE t171_switch_stmt FROM @sql;
EXECUTE t171_switch_stmt;
DEALLOCATE PREPARE t171_switch_stmt;