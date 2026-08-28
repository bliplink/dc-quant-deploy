CREATE TABLE IF NOT EXISTS `dc_order_idempotency` (
  `location` varchar(64) COLLATE utf8mb4_bin NOT NULL,
  `user_id` varchar(64) COLLATE utf8mb4_bin NOT NULL,
  `clord_id` varchar(255) COLLATE utf8mb4_bin NOT NULL,
  `order_id` varchar(255) COLLATE utf8mb4_bin NOT NULL,
  `request_hash` char(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `create_time` datetime(3) NOT NULL,
  PRIMARY KEY (`location`,`user_id`,`clord_id`),
  UNIQUE KEY `uk_dc_order_idempotency_order` (`order_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='客户端订单号幂等登记';
