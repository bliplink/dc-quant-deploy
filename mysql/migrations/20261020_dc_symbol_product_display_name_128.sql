-- Tenant-managed product_name accepts up to 128 characters. Preserve the
-- display name when cloning a global dc_symbol rule into a tenant contract.
-- Both columns previously had VARCHAR(45), despite tenant product_name=128.
-- Safe to apply repeatedly; no product rows are deleted or modified.
ALTER TABLE dc_symbol
  MODIFY COLUMN symbol_en_name VARCHAR(128) DEFAULT NULL COMMENT '产品英文名字',
  MODIFY COLUMN symbol_cn_name VARCHAR(128) DEFAULT NULL COMMENT '产品中文名';
