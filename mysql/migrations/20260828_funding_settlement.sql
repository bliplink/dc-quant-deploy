CREATE TABLE IF NOT EXISTS dc_funding_settlement (
  location varchar(45) NOT NULL DEFAULT '',
  user_id varchar(45) NOT NULL,
  security_id varchar(30) NOT NULL,
  settlement_time bigint NOT NULL COMMENT '计划结算时点(Unix毫秒)',
  mark_price decimal(35,9) NOT NULL,
  funding_rate decimal(35,16) NOT NULL,
  net_position decimal(35,9) NOT NULL,
  amount decimal(35,16) NOT NULL COMMENT '余额变动，正数入账、负数扣款',
  create_time varchar(30) NOT NULL,
  PRIMARY KEY (location, user_id, security_id, settlement_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='永续合约资金费幂等结算记录';
