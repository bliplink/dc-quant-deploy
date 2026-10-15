-- Durable queue for automatic trial-liquidity bootstrap.
-- Idempotent because deploy-saas.sh reapplies every migration on each deployment.

CREATE TABLE IF NOT EXISTS dc_tenant_liquidity_bootstrap (
  application_id varchar(64) COLLATE utf8mb4_bin NOT NULL,
  location varchar(64) COLLATE utf8mb4_bin NOT NULL,
  status varchar(32) NOT NULL DEFAULT 'PENDING',
  step varchar(32) NOT NULL DEFAULT 'CREATE_MAKER',
  funding_request_id varchar(128) COLLATE utf8mb4_bin NOT NULL,
  maker_user_id varchar(64) COLLATE utf8mb4_bin DEFAULT NULL,
  api_key varchar(255) COLLATE utf8mb4_bin DEFAULT NULL,
  funding_amount decimal(35,16) DEFAULT NULL,
  funding_confirmed tinyint(1) NOT NULL DEFAULT 0,
  attempts int unsigned NOT NULL DEFAULT 0,
  next_attempt_time datetime(3) DEFAULT NULL,
  lease_owner varchar(128) DEFAULT NULL,
  lease_until datetime(3) DEFAULT NULL,
  last_error_code varchar(64) DEFAULT NULL,
  last_error_message varchar(1000) DEFAULT NULL,
  create_time varchar(30) NOT NULL,
  update_time varchar(30) NOT NULL,
  complete_time datetime(3) DEFAULT NULL,
  PRIMARY KEY (application_id),
  UNIQUE KEY uq_tenant_liquidity_bootstrap_location (location),
  UNIQUE KEY uq_tenant_liquidity_bootstrap_funding (funding_request_id),
  KEY idx_tenant_liquidity_bootstrap_pending (status, next_attempt_time, create_time),
  KEY idx_tenant_liquidity_bootstrap_lease (status, lease_until)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Durable automatic trial-liquidity bootstrap queue';
