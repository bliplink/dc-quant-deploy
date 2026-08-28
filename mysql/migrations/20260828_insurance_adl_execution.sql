-- Keep synchronized with dbscripts/DB/saas_adl_execution_20260828.sql.
SET @schema_name = DATABASE();

SET @ddl = (SELECT IF(COUNT(*) = 0,
  'ALTER TABLE dc_liquidation_deficit ADD COLUMN adl_covered_amount decimal(35,16) NOT NULL DEFAULT 0 AFTER uncovered_amount',
  'SELECT 1') FROM information_schema.columns WHERE table_schema=@schema_name AND table_name='dc_liquidation_deficit' AND column_name='adl_covered_amount');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = (SELECT IF(COUNT(*) = 0,
  'ALTER TABLE dc_liquidation_deficit ADD COLUMN remaining_amount decimal(35,16) NOT NULL DEFAULT 0 AFTER adl_covered_amount',
  'SELECT 1') FROM information_schema.columns WHERE table_schema=@schema_name AND table_name='dc_liquidation_deficit' AND column_name='remaining_amount');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = (SELECT IF(COUNT(*) = 0,
  'ALTER TABLE dc_liquidation_deficit ADD COLUMN status varchar(20) NOT NULL DEFAULT ''OPEN'' AFTER remaining_amount',
  'SELECT 1') FROM information_schema.columns WHERE table_schema=@schema_name AND table_name='dc_liquidation_deficit' AND column_name='status');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = (SELECT IF(COUNT(*) = 0,
  'ALTER TABLE dc_adl_event ADD COLUMN liquidation_side varchar(10) DEFAULT NULL AFTER amount',
  'SELECT 1') FROM information_schema.columns WHERE table_schema=@schema_name AND table_name='dc_adl_event' AND column_name='liquidation_side');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = (SELECT IF(COUNT(*) = 0,
  'ALTER TABLE dc_adl_event ADD COLUMN reference_price decimal(35,16) DEFAULT NULL AFTER liquidation_side',
  'SELECT 1') FROM information_schema.columns WHERE table_schema=@schema_name AND table_name='dc_adl_event' AND column_name='reference_price');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = (SELECT IF(COUNT(*) = 0,
  'ALTER TABLE dc_adl_event ADD COLUMN adl_amount decimal(35,16) NOT NULL DEFAULT 0 AFTER reference_price',
  'SELECT 1') FROM information_schema.columns WHERE table_schema=@schema_name AND table_name='dc_adl_event' AND column_name='adl_amount');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = (SELECT IF(COUNT(*) = 0,
  'ALTER TABLE dc_adl_event ADD COLUMN remaining_amount decimal(35,16) NOT NULL DEFAULT 0 AFTER adl_amount',
  'SELECT 1') FROM information_schema.columns WHERE table_schema=@schema_name AND table_name='dc_adl_event' AND column_name='remaining_amount');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = (SELECT IF(COUNT(*) = 0,
  'ALTER TABLE dc_adl_event ADD COLUMN candidate_count int NOT NULL DEFAULT 0 AFTER remaining_amount',
  'SELECT 1') FROM information_schema.columns WHERE table_schema=@schema_name AND table_name='dc_adl_event' AND column_name='candidate_count');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = (SELECT IF(COUNT(*) = 0,
  'ALTER TABLE dc_adl_event ADD COLUMN completed_time varchar(30) DEFAULT NULL AFTER update_time',
  'SELECT 1') FROM information_schema.columns WHERE table_schema=@schema_name AND table_name='dc_adl_event' AND column_name='completed_time');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

CREATE TABLE IF NOT EXISTS dc_adl_ledger (
  location varchar(45) NOT NULL DEFAULT '',
  liquidation_order_id varchar(255) NOT NULL,
  rank_no int NOT NULL,
  liquidated_user_id varchar(45) NOT NULL,
  candidate_user_id varchar(45) NOT NULL,
  security_id varchar(30) NOT NULL,
  position_side varchar(10) NOT NULL,
  reference_price decimal(35,16) NOT NULL,
  profit_rate decimal(35,16) NOT NULL,
  effective_leverage decimal(35,16) NOT NULL,
  position_before decimal(35,9) NOT NULL,
  position_after decimal(35,9) NOT NULL,
  reduced_quantity decimal(35,9) NOT NULL,
  realized_pnl decimal(35,16) NOT NULL,
  allocated_amount decimal(35,16) NOT NULL,
  released_margin decimal(35,16) NOT NULL,
  balance_before decimal(35,16) NOT NULL,
  balance_after decimal(35,16) NOT NULL,
  create_time varchar(30) NOT NULL,
  PRIMARY KEY (location, liquidation_order_id, rank_no),
  KEY idx_adl_candidate_time (location, candidate_user_id, create_time),
  KEY idx_adl_symbol_time (location, security_id, create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Automatic deleveraging allocation ledger';

UPDATE dc_liquidation_deficit
SET remaining_amount = uncovered_amount
WHERE remaining_amount = 0 AND uncovered_amount > 0 AND adl_covered_amount = 0;
