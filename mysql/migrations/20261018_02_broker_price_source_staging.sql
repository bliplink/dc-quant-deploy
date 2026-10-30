-- Broker Price activation is independent of Maker liquidity handover.
-- price_source stays SYSTEM while a Broker price source is PREPARING.
-- This requires 20261018_broker_tenant_sources.sql first.
SET @db = DATABASE();
SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=@db
 AND TABLE_NAME='dc_tenant' AND COLUMN_NAME='price_switch_state')=0,
 "ALTER TABLE dc_tenant ADD COLUMN price_switch_state ENUM('ACTIVE','PREPARING','FAILED') NOT NULL DEFAULT 'ACTIVE'",
 'SELECT 1');
PREPARE ps FROM @sql; EXECUTE ps; DEALLOCATE PREPARE ps;
SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=@db
 AND TABLE_NAME='dc_tenant' AND COLUMN_NAME='pending_price_source')=0,
 "ALTER TABLE dc_tenant ADD COLUMN pending_price_source ENUM('SYSTEM','BROKER') DEFAULT NULL",
 'SELECT 1');
PREPARE pps FROM @sql; EXECUTE pps; DEALLOCATE PREPARE pps;
