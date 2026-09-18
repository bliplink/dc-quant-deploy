-- Tenant desired service routing policy.
-- Stores desired policy only; it does not migrate Order/MD/Trade state by itself.
CREATE TABLE IF NOT EXISTS tenant_service_route (
  location varchar(64) COLLATE utf8mb4_bin NOT NULL,
  service_type varchar(16) COLLATE utf8mb4_bin NOT NULL,
  route_mode varchar(16) COLLATE utf8mb4_bin NOT NULL DEFAULT 'SYSTEM',
  cluster_id varchar(128) COLLATE utf8mb4_bin DEFAULT NULL,
  enabled tinyint(1) NOT NULL DEFAULT 1,
  version bigint unsigned NOT NULL DEFAULT 1,
  create_by varchar(64) DEFAULT NULL,
  update_by varchar(64) DEFAULT NULL,
  create_time varchar(30) DEFAULT NULL,
  update_time varchar(30) DEFAULT NULL,
  PRIMARY KEY (location, service_type),
  KEY idx_tenant_service_route_mode (service_type, route_mode, enabled),
  CONSTRAINT fk_tenant_service_route_tenant FOREIGN KEY (location) REFERENCES dc_tenant(location)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Tenant desired logical service routing policy';

INSERT INTO tenant_service_route(location,service_type,route_mode,cluster_id,enabled,version)
SELECT location,'ORDER','SYSTEM',NULL,1,1 FROM dc_tenant
ON DUPLICATE KEY UPDATE location=VALUES(location);

INSERT INTO tenant_service_route(location,service_type,route_mode,cluster_id,enabled,version)
SELECT location,'MD','SYSTEM',NULL,1,1 FROM dc_tenant
ON DUPLICATE KEY UPDATE location=VALUES(location);

INSERT INTO tenant_service_route(location,service_type,route_mode,cluster_id,enabled,version)
SELECT location,'TRADE','SYSTEM',NULL,1,1 FROM dc_tenant
ON DUPLICATE KEY UPDATE location=VALUES(location);
