USE dc;

CREATE TABLE IF NOT EXISTS dc_adl_execution_v2 (
  location varchar(45) NOT NULL DEFAULT '',
  adl_execution_id varchar(255) NOT NULL,
  liquidation_order_id varchar(255) NOT NULL,
  rank_no int NOT NULL,
  liquidated_user_id varchar(45) NOT NULL,
  candidate_user_id varchar(45) NOT NULL,
  security_id varchar(30) NOT NULL,
  bankrupt_side varchar(10) NOT NULL,
  candidate_position_side varchar(10) NOT NULL,
  execution_price decimal(35,16) NOT NULL,
  quantity decimal(35,9) NOT NULL,
  profit_rate decimal(35,16) NOT NULL,
  effective_leverage decimal(35,16) NOT NULL,
  realized_pnl decimal(35,16) NOT NULL,
  released_margin decimal(35,16) NOT NULL,
  position_before decimal(35,9) NOT NULL,
  position_after decimal(35,9) NOT NULL,
  balance_before decimal(35,16) NOT NULL,
  balance_after decimal(35,16) NOT NULL,
  create_time varchar(30) NOT NULL,
  PRIMARY KEY (location, adl_execution_id),
  KEY idx_adl_v2_liquidation (location, liquidation_order_id, rank_no),
  KEY idx_adl_v2_candidate (location, candidate_user_id, create_time),
  KEY idx_adl_v2_symbol (location, security_id, create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Position-based automatic deleveraging execution ledger';
