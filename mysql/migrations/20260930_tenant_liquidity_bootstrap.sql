-- Durable hand-off from automatic tenant approval to trial liquidity setup.
-- Approval only enqueues this work; no account, API key, cash or Robot is
-- created in the approval transaction. A worker must prove each step before
-- advancing and may not retry cash without a durable idempotent TradeSvr API.
CREATE TABLE IF NOT EXISTS dc_tenant_liquidity_bootstrap (
  application_id varchar(64) COLLATE utf8mb4_bin NOT NULL,
  location varchar(64) COLLATE utf8mb4_bin NOT NULL,
  status varchar(24) NOT NULL DEFAULT 'PENDING',
  step varchar(32) NOT NULL DEFAULT 'CREATE_MAKER',
  funding_request_id varchar(128) COLLATE utf8mb4_bin NOT NULL,
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
