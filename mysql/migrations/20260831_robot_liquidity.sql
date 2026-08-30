-- RobotSvr runtime lease, external hedge journal and sweep lookup support.
-- Idempotent because deploy-saas.sh reapplies every migration on each deployment.

DROP PROCEDURE IF EXISTS dc_robot_add_column;
DELIMITER $$
CREATE PROCEDURE dc_robot_add_column(IN p_column varchar(64), IN p_definition text)
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

CALL dc_robot_add_column('runtime_owner', 'runtime_owner varchar(128) DEFAULT NULL');
CALL dc_robot_add_column('runtime_lease_until', 'runtime_lease_until datetime(3) DEFAULT NULL');
CALL dc_robot_add_column('last_error_code', 'last_error_code varchar(64) DEFAULT NULL');
CALL dc_robot_add_column('last_error_message', 'last_error_message varchar(1000) DEFAULT NULL');
CALL dc_robot_add_column('last_reference_price', 'last_reference_price decimal(35,16) DEFAULT NULL');
CALL dc_robot_add_column('open_order_count', 'open_order_count int unsigned NOT NULL DEFAULT 0');
CALL dc_robot_add_column('quote_source', 'quote_source varchar(32) NOT NULL DEFAULT ''APSSVR_BINANCE_DEPTH'' AFTER api_key');
DROP PROCEDURE dc_robot_add_column;

ALTER TABLE dc_tenant_robot
  MODIFY quote_source varchar(32) NOT NULL DEFAULT 'APSSVR_BINANCE_DEPTH',
  MODIFY bid_levels smallint unsigned NOT NULL DEFAULT 10,
  MODIFY ask_levels smallint unsigned NOT NULL DEFAULT 10;

DROP PROCEDURE IF EXISTS dc_robot_add_index;
DELIMITER $$
CREATE PROCEDURE dc_robot_add_index()
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.statistics
    WHERE table_schema=DATABASE() AND table_name='dc_orders' AND index_name='idx_robot_sweep'
  ) THEN
    ALTER TABLE dc_orders
      ADD KEY idx_robot_sweep (location,security_id,ord_status,side,price,transact_time);
  END IF;
END$$
DELIMITER ;
CALL dc_robot_add_index();
DROP PROCEDURE dc_robot_add_index;

CREATE TABLE IF NOT EXISTS dc_robot_hedge_execution (
  hedge_id varchar(64) COLLATE utf8mb4_bin NOT NULL,
  location varchar(64) COLLATE utf8mb4_bin NOT NULL,
  robot_id varchar(64) COLLATE utf8mb4_bin NOT NULL,
  security_id varchar(64) COLLATE utf8mb4_bin NOT NULL,
  venue varchar(64) NOT NULL,
  account_ref varchar(255) NOT NULL,
  client_order_id varchar(36) COLLATE utf8mb4_bin NOT NULL,
  side varchar(8) NOT NULL,
  requested_qty decimal(35,16) NOT NULL,
  executed_qty decimal(35,16) NOT NULL DEFAULT 0,
  target_hedge_position decimal(35,16) NOT NULL,
  average_price decimal(35,16) DEFAULT NULL,
  status varchar(24) NOT NULL,
  external_order_id varchar(128) DEFAULT NULL,
  external_status varchar(32) DEFAULT NULL,
  raw_response text DEFAULT NULL,
  error_message varchar(1000) DEFAULT NULL,
  request_time datetime(3) NOT NULL,
  update_time datetime(3) NOT NULL,
  PRIMARY KEY (hedge_id),
  UNIQUE KEY uq_robot_hedge_client_order (location,robot_id,client_order_id),
  KEY idx_robot_hedge_status (location,robot_id,status,request_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Idempotent external hedge execution journal';
