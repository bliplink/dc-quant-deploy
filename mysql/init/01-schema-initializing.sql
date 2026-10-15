-- Created on first MySQL database initialization, BEFORE the actual schema.
-- Prevents a restarted database from appearing healthy after a partial DDL
-- failure. The last migration script alone may mark this install complete.
USE dc;
CREATE TABLE IF NOT EXISTS dc_fresh_schema_install_status (
  marker varchar(24) NOT NULL PRIMARY KEY,
  ready tinyint(1) NOT NULL,
  updated_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;
INSERT INTO dc_fresh_schema_install_status(marker,ready)
VALUES ('all-migrations-done',0)
ON DUPLICATE KEY UPDATE ready=0,updated_at=CURRENT_TIMESTAMP;
