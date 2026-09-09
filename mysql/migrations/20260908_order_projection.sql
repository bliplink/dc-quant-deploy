CREATE TABLE IF NOT EXISTS `dc_order_projection_event` (
  `event_id` varchar(160) NOT NULL,
  `partition_id` varchar(32) NOT NULL,
  `source_epoch` bigint NOT NULL,
  `journal_seq` bigint NOT NULL,
  `event_type` varchar(64) NOT NULL,
  `source_node` varchar(64) DEFAULT NULL,
  `event_time` bigint NOT NULL,
  `payload` longtext NOT NULL,
  `create_time` datetime(3) NOT NULL,
  PRIMARY KEY (`event_id`),
  UNIQUE KEY `uk_dc_order_projection_partition_seq` (`partition_id`,`source_epoch`,`journal_seq`),
  KEY `idx_dc_order_projection_create_time` (`create_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `dc_order_projection_watermark` (
  `partition_id` varchar(32) NOT NULL,
  `source_epoch` bigint NOT NULL DEFAULT 0,
  `journal_seq` bigint NOT NULL DEFAULT 0,
  `event_id` varchar(160) DEFAULT NULL,
  `update_time` datetime(3) NOT NULL,
  PRIMARY KEY (`partition_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
