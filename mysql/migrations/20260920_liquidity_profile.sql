-- Reusable tenant liquidity profiles and Robot profile provenance.
-- Idempotent because deploy-saas.sh reapplies every migration on each deployment.

CREATE TABLE IF NOT EXISTS dc_tenant_liquidity_profile (
  location varchar(64) COLLATE utf8mb4_bin NOT NULL,
  profile_id varchar(64) COLLATE utf8mb4_bin NOT NULL,
  profile_name varchar(128) NOT NULL,
  description varchar(500) DEFAULT NULL,
  profile_config json NOT NULL,
  version bigint unsigned NOT NULL DEFAULT 1,
  status varchar(24) NOT NULL DEFAULT 'ACTIVE',
  create_by varchar(64) NOT NULL,
  update_by varchar(64) NOT NULL,
  create_time varchar(30) NOT NULL,
  update_time varchar(30) NOT NULL,
  PRIMARY KEY (location, profile_id),
  UNIQUE KEY uq_tenant_liquidity_profile_name (location, profile_name),
  KEY idx_tenant_liquidity_profile_status (location, status, update_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Tenant reusable Robot liquidity configuration profiles';

DROP PROCEDURE IF EXISTS dc_liquidity_profile_add_robot_column;
DELIMITER $$
CREATE PROCEDURE dc_liquidity_profile_add_robot_column(IN p_column varchar(64), IN p_definition text)
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema=DATABASE() AND table_name='dc_tenant_robot' AND column_name=p_column
  ) THEN
    SET @ddl = CONCAT('ALTER TABLE dc_tenant_robot ADD COLUMN ', p_definition);
    PREPARE statement_handle FROM @ddl;
    EXECUTE statement_handle;
    DEALLOCATE PREPARE statement_handle;
  END IF;
END$$
DELIMITER ;

CALL dc_liquidity_profile_add_robot_column(
  'liquidity_profile_id',
  'liquidity_profile_id varchar(64) COLLATE utf8mb4_bin DEFAULT NULL AFTER strategy_config'
);
CALL dc_liquidity_profile_add_robot_column(
  'liquidity_profile_version',
  'liquidity_profile_version bigint unsigned DEFAULT NULL AFTER liquidity_profile_id'
);

DROP PROCEDURE dc_liquidity_profile_add_robot_column;
