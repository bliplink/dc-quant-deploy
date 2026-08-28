UPDATE dc_orders_position SET location = '' WHERE location IS NULL;
ALTER TABLE dc_orders_position
  MODIFY location varchar(45) NOT NULL DEFAULT '',
  DROP PRIMARY KEY,
  ADD PRIMARY KEY (location, user_id, security_id);

UPDATE dc_users_balance SET location = '' WHERE location IS NULL;
ALTER TABLE dc_users_balance
  MODIFY location varchar(30) NOT NULL DEFAULT '',
  DROP PRIMARY KEY,
  ADD PRIMARY KEY (location, user_id);

UPDATE dc_users_config SET location = '' WHERE location IS NULL;
ALTER TABLE dc_users_config
  MODIFY location varchar(30) NOT NULL DEFAULT '',
  DROP PRIMARY KEY,
  ADD PRIMARY KEY (location, user_id);

UPDATE dc_users_symbol_config SET location = '' WHERE location IS NULL;
ALTER TABLE dc_users_symbol_config
  MODIFY location varchar(30) NOT NULL DEFAULT '',
  DROP PRIMARY KEY,
  ADD PRIMARY KEY (location, user_id, security_id);
