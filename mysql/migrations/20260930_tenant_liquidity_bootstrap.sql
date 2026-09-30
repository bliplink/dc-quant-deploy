-- Durable hand-off from automatic tenant approval to trial liquidity setup.
-- Approval only enqueues this work; no account, API key, cash or Robot is
-- created in the approval transaction. The worker may retry an ambiguous
-- Demo-only cash request up to three times when explicitly enabled locally.
-- TradeSvr cashIn is not request-idempotent: never enable this for real funds.
CREATE TABLE IF NOT EXISTS dc_tenant_liquidity_bootstrap (
  application_id varchar(64) COLLATE utf8mb4_bin NOT NULL,
  location varchar(64) COLLATE utf8mb4_bin NOT NULL,
  status varchar(24) NOT NULL DEFAULT 'PENDING',
  step varchar(32) NOT NULL DEFAULT 'CREATE_MAKER',
  funding_request_id varchar(128) COLLATE utf8mb4_bin NOT NULL,
  maker_user_id varchar(64) COLLATE utf8mb4_bin DEFAULT NULL,
  api_key varchar(255) COLLATE utf8mb4_bin DEFAULT NULL,
  funding_amount decimal(35,16) DEFAULT NULL,
  funding_confirmed tinyint(1) NOT NULL DEFAULT 0,
  complete_time datetime(3) DEFAULT NULL,
  attempts int unsigned NOT NULL DEFAULT 0,
  next_attempt_time datetime(3) DEFAULT NULL,
  lease_owner varchar(128) DEFAULT NULL,
  lease_until datetime(3) DEFAULT NULL,
  last_error_code varchar(64) DEFAULT NULL,
  last_error_message varchar(1000) DEFAULT NULL,
  create_time varchar(30) NOT NULL,
  update_time varchar(30) NOT NULL,
  PRIMARY KEY (application_id),
  UNIQUE KEY uq_liquidity_bootstrap_location (location),
  UNIQUE KEY uq_liquidity_bootstrap_funding (funding_request_id),
  KEY idx_liquidity_bootstrap_ready (status,next_attempt_time,lease_until)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Durable trial liquidity initialization after automatic tenant approval';

-- The first enqueue-only release created the table without worker columns.
-- Deploy reapplies migrations, so upgrade existing installations in place.
DROP PROCEDURE IF EXISTS dc_liquidity_bootstrap_add_column;
DELIMITER $$
CREATE PROCEDURE dc_liquidity_bootstrap_add_column(IN p_column varchar(64), IN p_definition text)
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema=DATABASE()
      AND table_name='dc_tenant_liquidity_bootstrap'
      AND column_name=p_column
  ) THEN
    SET @bootstrap_ddl = CONCAT('ALTER TABLE dc_tenant_liquidity_bootstrap ADD COLUMN ', p_definition);
    PREPARE bootstrap_stmt FROM @bootstrap_ddl;
    EXECUTE bootstrap_stmt;
    DEALLOCATE PREPARE bootstrap_stmt;
  END IF;
END$$
DELIMITER ;

CALL dc_liquidity_bootstrap_add_column('maker_user_id',
  'maker_user_id varchar(64) COLLATE utf8mb4_bin DEFAULT NULL AFTER funding_request_id');
CALL dc_liquidity_bootstrap_add_column('api_key',
  'api_key varchar(255) COLLATE utf8mb4_bin DEFAULT NULL AFTER maker_user_id');
CALL dc_liquidity_bootstrap_add_column('funding_amount',
  'funding_amount decimal(35,16) DEFAULT NULL AFTER api_key');
CALL dc_liquidity_bootstrap_add_column('funding_confirmed',
  'funding_confirmed tinyint(1) NOT NULL DEFAULT 0 AFTER funding_amount');
CALL dc_liquidity_bootstrap_add_column('complete_time',
  'complete_time datetime(3) DEFAULT NULL AFTER funding_confirmed');

DROP PROCEDURE dc_liquidity_bootstrap_add_column;
