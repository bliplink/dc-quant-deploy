USE dc;

-- Fresh-install companion to mysql/migrations/20260903_bankruptcy_takeover.sql.
CREATE TABLE IF NOT EXISTS dc_bankruptcy_transfer (
  location varchar(45) NOT NULL DEFAULT '',
  liquidation_order_id varchar(255) NOT NULL,
  liquidation_side varchar(10) NOT NULL,
  user_id varchar(45) NOT NULL,
  security_id varchar(30) NOT NULL,
  bankruptcy_price decimal(35,16) NOT NULL,
  requested_quantity decimal(35,9) NOT NULL,
  insurance_quantity decimal(35,9) NOT NULL DEFAULT 0,
  adl_quantity decimal(35,9) NOT NULL DEFAULT 0,
  insurance_notional decimal(35,16) NOT NULL DEFAULT 0,
  settlement_pnl decimal(35,16) NOT NULL DEFAULT 0,
  balance_after decimal(35,16) NOT NULL DEFAULT 0,
  used_margin_after decimal(35,16) NOT NULL DEFAULT 0,
  status varchar(24) NOT NULL,
  create_time varchar(30) NOT NULL,
  update_time varchar(30) NOT NULL,
  completed_time varchar(30) DEFAULT NULL,
  PRIMARY KEY (location, liquidation_order_id, liquidation_side),
  KEY idx_bankruptcy_symbol_status (location, security_id, status, create_time),
  KEY idx_bankruptcy_user_time (location, user_id, create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Position-based bankruptcy takeover and insurance/ADL risk ledger';
