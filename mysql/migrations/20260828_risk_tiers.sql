SET @schema_name = DATABASE();
SET @add_risk_tiers = (
  SELECT IF(COUNT(*) = 0,
    'ALTER TABLE dc_symbol ADD COLUMN risk_tiers json DEFAULT NULL COMMENT ''名义价值风险阶梯(JSON)'' AFTER risk_step',
    'SELECT 1')
  FROM information_schema.columns
  WHERE table_schema = @schema_name AND table_name = 'dc_symbol' AND column_name = 'risk_tiers'
);
PREPARE stmt FROM @add_risk_tiers;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
