-- Common business projections are MySQL read models, NOT Common WAL/HA state.
-- Keep fresh-install and recurring deployment DDL identical. These tables
-- previously existed only because ProjectionSvr created them on startup.
-- Never copy prior-generation rows/watermarks into a new Common namespace.

CREATE TABLE IF NOT EXISTS `dc_trade_projection_event` (
  `event_id` varchar(160) NOT NULL,
  `partition_id` varchar(64) NOT NULL,
  `source_epoch` bigint NOT NULL,
  `journal_seq` bigint NOT NULL,
  `event_type` varchar(64) NOT NULL,
  `source_node` varchar(128) DEFAULT NULL,
  `event_time` bigint NOT NULL,
  `payload` longtext NOT NULL,
  `create_time` datetime(3) NOT NULL,
  PRIMARY KEY (`partition_id`,`source_epoch`,`journal_seq`),
  KEY `idx_trade_projection_event_id` (`event_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `dc_trade_projection_mutation` (
  `event_id` varchar(160) NOT NULL,
  `mutation_index` int NOT NULL,
  `location` varchar(128) NOT NULL,
  `request_id` varchar(160) DEFAULT NULL,
  `source_type` varchar(64) DEFAULT NULL,
  `entity_type` varchar(64) NOT NULL,
  `operation` varchar(32) NOT NULL,
  `entity_key` varchar(512) DEFAULT NULL,
  `payload` longtext,
  `create_time` datetime(3) NOT NULL,
  `partition_id` varchar(64) NOT NULL,
  `source_epoch` bigint NOT NULL,
  `journal_seq` bigint NOT NULL,
  PRIMARY KEY (`partition_id`,`source_epoch`,`journal_seq`,`mutation_index`),
  KEY `idx_trade_projection_event_id` (`event_id`),
  KEY `idx_trade_projection_location` (`location`,`entity_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `dc_trade_projection_watermark` (
  `partition_id` varchar(64) NOT NULL,
  `source_epoch` bigint NOT NULL DEFAULT 0,
  `journal_seq` bigint NOT NULL DEFAULT 0,
  `event_id` varchar(160) DEFAULT NULL,
  `update_time` datetime(3) NOT NULL,
  PRIMARY KEY (`partition_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `dc_trade_financial_readmodel_cursor` (
  `partition_id` varchar(64) NOT NULL,
  `source_epoch` bigint NOT NULL,
  `journal_seq` bigint NOT NULL,
  `update_time` datetime(3) NOT NULL,
  PRIMARY KEY (`partition_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;