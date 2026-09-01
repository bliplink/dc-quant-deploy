
CREATE TABLE IF NOT EXISTS dc_tenant_hedge_account (
  location varchar(64) COLLATE utf8mb4_bin NOT NULL,
  account_ref varchar(64) NOT NULL,
  venue varchar(32) NOT NULL DEFAULT 'BNFutures',
  api_key_ciphertext varchar(1024) NOT NULL,
  secret_key_ciphertext varchar(1024) NOT NULL,
  enabled tinyint(1) NOT NULL DEFAULT 1,
  create_by varchar(64) DEFAULT NULL,
  update_by varchar(64) DEFAULT NULL,
  create_time varchar(30) NOT NULL,
  update_time varchar(30) NOT NULL,
  PRIMARY KEY (location, account_ref),
  CONSTRAINT fk_tenant_hedge_account_tenant FOREIGN KEY (location) REFERENCES dc_tenant(location)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='AES-GCM encrypted external hedge credentials scoped by tenant';
