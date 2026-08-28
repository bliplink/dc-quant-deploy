CREATE TABLE IF NOT EXISTS dc_insurance_fund (
  location varchar(45) NOT NULL DEFAULT '',
  security_id varchar(30) NOT NULL,
  balance decimal(35,16) NOT NULL DEFAULT 0,
  update_time varchar(30) NOT NULL,
  PRIMARY KEY (location, security_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='强平保险基金';

CREATE TABLE IF NOT EXISTS dc_insurance_fund_ledger (
  location varchar(45) NOT NULL DEFAULT '',
  request_id varchar(64) NOT NULL,
  security_id varchar(30) NOT NULL,
  operation varchar(20) NOT NULL,
  amount decimal(35,16) NOT NULL,
  balance_before decimal(35,16) NOT NULL,
  balance_after decimal(35,16) NOT NULL,
  operator_id varchar(45) NOT NULL,
  remark varchar(255) DEFAULT NULL,
  create_time varchar(30) NOT NULL,
  PRIMARY KEY (location, request_id),
  KEY idx_insurance_fund_ledger_symbol_time (location, security_id, create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Insurance fund operation ledger';

CREATE TABLE IF NOT EXISTS dc_liquidation_deficit (
  location varchar(45) NOT NULL DEFAULT '',
  liquidation_order_id varchar(255) NOT NULL,
  user_id varchar(45) NOT NULL,
  security_id varchar(30) NOT NULL,
  deficit_amount decimal(35,16) NOT NULL,
  covered_amount decimal(35,16) NOT NULL,
  uncovered_amount decimal(35,16) NOT NULL,
  create_time varchar(30) NOT NULL,
  PRIMARY KEY (location, liquidation_order_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='穿仓与保险基金赔付流水';

CREATE TABLE IF NOT EXISTS dc_adl_event (
  location varchar(45) NOT NULL DEFAULT '',
  liquidation_order_id varchar(255) NOT NULL,
  user_id varchar(45) NOT NULL,
  security_id varchar(30) NOT NULL,
  amount decimal(35,16) NOT NULL,
  status varchar(20) NOT NULL,
  create_time varchar(30) NOT NULL,
  update_time varchar(30) NOT NULL,
  PRIMARY KEY (location, liquidation_order_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='自动减仓事件';
