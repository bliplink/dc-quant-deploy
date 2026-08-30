-- Keep synchronized with dbscripts/DB/saas_users_location_identity_20260830.sql.
UPDATE dc_users SET location='0' WHERE location IS NULL OR trim(location)='';
UPDATE dc_users SET user_id=user_name WHERE user_id IS NULL OR trim(user_id)='';

ALTER TABLE dc_users
  MODIFY user_id varchar(64) NOT NULL COMMENT '用户id',
  MODIFY location varchar(64) NOT NULL DEFAULT '0' COMMENT '多实体';

SET @primary_columns = (
  SELECT GROUP_CONCAT(column_name ORDER BY seq_in_index SEPARATOR ',')
  FROM information_schema.statistics
  WHERE table_schema=DATABASE() AND table_name='dc_users' AND index_name='PRIMARY'
);
SET @ddl = IF(@primary_columns='location,user_name', 'SELECT 1',
  IF(@primary_columns IS NULL, 'SELECT 1', 'ALTER TABLE dc_users DROP PRIMARY KEY'));
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = (
  SELECT IF(COUNT(*)=0, 'SELECT 1', 'ALTER TABLE dc_users DROP INDEX user_name')
  FROM information_schema.statistics
  WHERE table_schema=DATABASE() AND table_name='dc_users' AND index_name='user_name'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @primary_columns = (
  SELECT GROUP_CONCAT(column_name ORDER BY seq_in_index SEPARATOR ',')
  FROM information_schema.statistics
  WHERE table_schema=DATABASE() AND table_name='dc_users' AND index_name='PRIMARY'
);
SET @ddl = IF(@primary_columns='location,user_name', 'SELECT 1',
  'ALTER TABLE dc_users ADD PRIMARY KEY (location,user_name)');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = (
  SELECT IF(COUNT(*)=0,
    'ALTER TABLE dc_users ADD UNIQUE KEY uq_users_location_user_id (location,user_id)',
    'SELECT 1')
  FROM information_schema.statistics
  WHERE table_schema=DATABASE() AND table_name='dc_users' AND index_name='uq_users_location_user_id'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = (
  SELECT IF(COUNT(*)=0,
    'ALTER TABLE dc_users ADD KEY idx_users_user_name (user_name)',
    'SELECT 1')
  FROM information_schema.statistics
  WHERE table_schema=DATABASE() AND table_name='dc_users' AND index_name='idx_users_user_name'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

