CREATE TABLE `dc_audit_log` (
  `id` varchar(45) NOT NULL COMMENT 'ID序列号',
  `user_id` varchar(45) DEFAULT NULL COMMENT '操作人',
  `type` varchar(45) DEFAULT NULL COMMENT '类型',
  `status` varchar(45) DEFAULT NULL COMMENT '1:新增，2：更新，3删除',
  `ip` varchar(45) DEFAULT NULL COMMENT 'ip地址',
  `mac` varchar(45) DEFAULT NULL COMMENT 'mac地址',
  `terminal` varchar(45) DEFAULT NULL COMMENT '终端',
  `content` varchar(3000) DEFAULT NULL COMMENT '内容',
  `create_time` varchar(45) DEFAULT NULL COMMENT '创建时间',
  `close_by` varchar(45) DEFAULT NULL COMMENT '操作人',
  PRIMARY KEY (`id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC COMMENT='审计日志';

CREATE TABLE `dc_kols` (
  `kol_user_id` varchar(400) NOT NULL COMMENT '用户id',
  `referrer` varchar(255) DEFAULT NULL COMMENT '推荐码',
  `remark` varchar(500) DEFAULT NULL COMMENT '备注',
  `status` char(1) DEFAULT NULL COMMENT '审核状态，0：通过，2：待审核，3：不通过',
  `create_time` varchar(100) DEFAULT NULL COMMENT '创建时间',
  `update_time` varchar(100) DEFAULT NULL COMMENT '更新时间',
  `close_by` varchar(100) DEFAULT NULL COMMENT '操作人',
  `level1_rebate` decimal(35,2) DEFAULT NULL COMMENT '直客返佣比例',
  `level2_rebate` decimal(35,2) DEFAULT NULL COMMENT '二级返佣比例',
  `invited_count` int(11) DEFAULT NULL,
  `volume` decimal(35,9) DEFAULT NULL,
  PRIMARY KEY (`kol_user_id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC COMMENT='kol表';

CREATE TABLE `dc_kols_rpt_day` (
  `trade_date` varchar(45) NOT NULL COMMENT '交易日期',
  `kol_user_id` varchar(45) NOT NULL COMMENT 'kol用户id',
  `fee_amount` decimal(35,9) DEFAULT NULL COMMENT '累计返佣',
  `create_time` varchar(100) DEFAULT NULL COMMENT '创建时间',
  `update_time` varchar(100) DEFAULT NULL COMMENT '更新时间',
  `status` char(1) DEFAULT NULL COMMENT '上链状态，1：已上链，0：带上链，2：上链失败',
  `txid` varchar(255) DEFAULT NULL COMMENT 'txid',
  `invited_count` int(11) DEFAULT NULL,
  `volume` decimal(35,9) DEFAULT NULL,
  PRIMARY KEY (`trade_date`,`kol_user_id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC COMMENT='kol按天统计表';

CREATE TABLE `dc_kols_rpt_detail` (
  `trade_date` varchar(45) NOT NULL,
  `kol_user_id` varchar(45) NOT NULL COMMENT 'kol用户id',
  `user_id` varchar(45) NOT NULL COMMENT '用户id',
  `type` char(1) DEFAULT NULL COMMENT '返佣类型，1：直客，2：二级',
  `volume` decimal(35,9) DEFAULT NULL COMMENT '成交量(USDC)',
  `fee` decimal(35,9) DEFAULT NULL COMMENT '手续费(USDC)',
  `rebate` decimal(35,9) DEFAULT NULL COMMENT '返佣比例',
  `fee_amount` decimal(35,9) DEFAULT NULL COMMENT '返佣金额',
  `create_time` varchar(100) DEFAULT NULL COMMENT '创建时间',
  `update_time` varchar(100) DEFAULT NULL COMMENT '更新时间',
  PRIMARY KEY (`trade_date`,`kol_user_id`,`user_id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC COMMENT='返佣详情表';

CREATE TABLE `dc_modules` (
  `id` varchar(45) NOT NULL,
  `module_name` varchar(45) NOT NULL,
  `parent_id` varchar(45) NOT NULL,
  `terminal` varchar(45) DEFAULT NULL,
  `ip` varchar(45) DEFAULT NULL,
  `close_by` varchar(45) DEFAULT NULL,
  `remark` varchar(1000) DEFAULT NULL,
  `create_time` varchar(45) DEFAULT NULL,
  `update_time` varchar(45) DEFAULT NULL,
  `inf1` varchar(500) DEFAULT NULL,
  `inf2` varchar(500) DEFAULT NULL,
  `inf3` varchar(500) DEFAULT NULL,
  `inf4` varchar(500) DEFAULT NULL,
  `inf5` varchar(500) DEFAULT NULL,
  PRIMARY KEY (`id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `dc_modules_action` (
  `id` varchar(45) NOT NULL,
  `action_name` varchar(45) NOT NULL,
  `module_id` varchar(45) NOT NULL,
  `terminal` varchar(45) DEFAULT NULL,
  `ip` varchar(45) DEFAULT NULL,
  `close_by` varchar(45) DEFAULT NULL,
  `remark` varchar(1000) DEFAULT NULL,
  `create_time` varchar(45) DEFAULT NULL,
  `update_time` varchar(45) DEFAULT NULL,
  `inf1` varchar(500) DEFAULT NULL,
  `inf2` varchar(500) DEFAULT NULL,
  `inf3` varchar(500) DEFAULT NULL,
  `inf4` varchar(500) DEFAULT NULL,
  `inf5` varchar(500) DEFAULT NULL,
  PRIMARY KEY (`id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `dc_orders` (
  `order_id` varchar(255) NOT NULL COMMENT '内部唯一订单号',
  `user_id` varchar(64) NOT NULL COMMENT '注册用户id',
  `algo_name` varchar(45) DEFAULT NULL,
  `account_id` varchar(64) DEFAULT NULL COMMENT '交易结算账户id',
  `currency` varchar(32) DEFAULT NULL COMMENT '结算货币',
  `market_indicator` varchar(32) NOT NULL COMMENT '市场',
  `security_id` varchar(32) DEFAULT NULL COMMENT '产品代码',
  `symbol` varchar(32) DEFAULT NULL COMMENT '产品名称',
  `clord_id` varchar(255) DEFAULT NULL COMMENT '外部传入订单号',
  `side` varchar(32) DEFAULT NULL COMMENT '订单方向: 1~做多, 2~做空',
  `ord_type` varchar(45) DEFAULT NULL COMMENT '订单类型',
  `timeinforce` varchar(45) DEFAULT NULL COMMENT 'GTC,IOC,FOK,PostOnly',
  `oc_type` varchar(45) DEFAULT NULL COMMENT '开平仓',
  `position_side` varchar(16) DEFAULT NULL COMMENT '持仓方向',
  `reduce_only` tinyint(1) NOT NULL DEFAULT '0' COMMENT '只减仓',
  `price` decimal(60,8) DEFAULT NULL COMMENT '订单价格',
  `order_qty` decimal(35,8) DEFAULT NULL COMMENT '订单数量',
  `ord_status` varchar(45) DEFAULT NULL COMMENT '订单状态',
  `ord_Rej_Reason` varchar(45) DEFAULT NULL COMMENT '错误代码',
  `reject_Text` varchar(5000) DEFAULT NULL COMMENT '错误原因',
  `leaves_qty` decimal(35,9) DEFAULT NULL COMMENT '剩余数量',
  `cum_qty` decimal(35,9) DEFAULT NULL COMMENT '累计已成交数量',
  `take_profit_price` decimal(35,9) DEFAULT NULL COMMENT '止盈价',
  `stop_loss_price` decimal(35,9) DEFAULT NULL COMMENT '止损价',
  `trigger_type` varchar(45) DEFAULT NULL COMMENT '触发类型',
  `trigger_price` decimal(35,9) DEFAULT NULL COMMENT '触发价格',
  `trigger_condition` varchar(45) DEFAULT NULL COMMENT '触发条件',
  `create_time` varchar(45) DEFAULT NULL COMMENT '创建时间',
  `update_time` varchar(30) DEFAULT NULL COMMENT '更新时间',
  `close_by` varchar(30) DEFAULT NULL COMMENT '最后操作人',
  `location` varchar(30) DEFAULT NULL COMMENT '多实体',
  `transact_time` varchar(45) DEFAULT NULL,
  `info1` varchar(255) DEFAULT NULL,
  `info2` varchar(255) DEFAULT NULL,
  `info3` varchar(45) DEFAULT NULL,
  `info4` varchar(45) DEFAULT NULL,
  `info5` varchar(45) DEFAULT NULL,
  `maker` int(11) DEFAULT NULL,
  PRIMARY KEY (`order_id`,`user_id`) USING BTREE,
  KEY `query_index` (`user_id`,`security_id`,`side`,`ord_type`,`order_id`,`ord_status`) USING BTREE,
  KEY `idx_robot_sweep` (`location`,`security_id`,`ord_status`,`side`,`price`,`transact_time`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC COMMENT='订单表';

CREATE TABLE `dc_order_idempotency` (
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

CREATE TABLE `dc_funding_settlement` (
  `location` varchar(45) NOT NULL DEFAULT '',
  `user_id` varchar(45) NOT NULL,
  `security_id` varchar(30) NOT NULL,
  `settlement_time` bigint NOT NULL COMMENT '计划结算时点(Unix毫秒)',
  `mark_price` decimal(35,9) NOT NULL,
  `funding_rate` decimal(35,16) NOT NULL,
  `net_position` decimal(35,9) NOT NULL,
  `amount` decimal(35,16) NOT NULL COMMENT '余额变动，正数入账、负数扣款',
  `create_time` varchar(30) NOT NULL,
  PRIMARY KEY (`location`,`user_id`,`security_id`,`settlement_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='永续合约资金费幂等结算记录';

CREATE TABLE `dc_insurance_fund` (
  `location` varchar(45) NOT NULL DEFAULT '',
  `security_id` varchar(30) NOT NULL,
  `balance` decimal(35,16) NOT NULL DEFAULT 0,
  `update_time` varchar(30) NOT NULL,
  PRIMARY KEY (`location`,`security_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='强平保险基金';

CREATE TABLE `dc_liquidation_deficit` (
  `location` varchar(45) NOT NULL DEFAULT '',
  `liquidation_order_id` varchar(255) NOT NULL,
  `user_id` varchar(45) NOT NULL,
  `security_id` varchar(30) NOT NULL,
  `deficit_amount` decimal(35,16) NOT NULL,
  `covered_amount` decimal(35,16) NOT NULL,
  `uncovered_amount` decimal(35,16) NOT NULL,
  `adl_covered_amount` decimal(35,16) NOT NULL DEFAULT 0,
  `remaining_amount` decimal(35,16) NOT NULL DEFAULT 0,
  `status` varchar(20) NOT NULL DEFAULT 'OPEN',
  `create_time` varchar(30) NOT NULL,
  PRIMARY KEY (`location`,`liquidation_order_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='穿仓与保险基金赔付流水';

CREATE TABLE `dc_adl_event` (
  `location` varchar(45) NOT NULL DEFAULT '',
  `liquidation_order_id` varchar(255) NOT NULL,
  `user_id` varchar(45) NOT NULL,
  `security_id` varchar(30) NOT NULL,
  `amount` decimal(35,16) NOT NULL,
  `liquidation_side` varchar(10) DEFAULT NULL,
  `reference_price` decimal(35,16) DEFAULT NULL,
  `adl_amount` decimal(35,16) NOT NULL DEFAULT 0,
  `remaining_amount` decimal(35,16) NOT NULL DEFAULT 0,
  `candidate_count` int NOT NULL DEFAULT 0,
  `status` varchar(20) NOT NULL,
  `create_time` varchar(30) NOT NULL,
  `update_time` varchar(30) NOT NULL,
  `completed_time` varchar(30) DEFAULT NULL,
  PRIMARY KEY (`location`,`liquidation_order_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='自动减仓事件';

CREATE TABLE `dc_adl_ledger` (
  `location` varchar(45) NOT NULL DEFAULT '',
  `liquidation_order_id` varchar(255) NOT NULL,
  `rank_no` int NOT NULL,
  `liquidated_user_id` varchar(45) NOT NULL,
  `candidate_user_id` varchar(45) NOT NULL,
  `security_id` varchar(30) NOT NULL,
  `position_side` varchar(10) NOT NULL,
  `reference_price` decimal(35,16) NOT NULL,
  `profit_rate` decimal(35,16) NOT NULL,
  `effective_leverage` decimal(35,16) NOT NULL,
  `position_before` decimal(35,9) NOT NULL,
  `position_after` decimal(35,9) NOT NULL,
  `reduced_quantity` decimal(35,9) NOT NULL,
  `realized_pnl` decimal(35,16) NOT NULL,
  `allocated_amount` decimal(35,16) NOT NULL,
  `released_margin` decimal(35,16) NOT NULL,
  `balance_before` decimal(35,16) NOT NULL,
  `balance_after` decimal(35,16) NOT NULL,
  `create_time` varchar(30) NOT NULL,
  PRIMARY KEY (`location`,`liquidation_order_id`,`rank_no`),
  KEY `idx_adl_candidate_time` (`location`,`candidate_user_id`,`create_time`),
  KEY `idx_adl_symbol_time` (`location`,`security_id`,`create_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Automatic deleveraging allocation ledger';

CREATE TABLE `dc_orders_execorders` (
  `exec_id` varchar(300) NOT NULL COMMENT '撮合成交对id',
  `order_id` varchar(45) DEFAULT NULL COMMENT '订单id',
  `user_id` varchar(64) NOT NULL COMMENT '注册用户id',
  `account_id` varchar(64) DEFAULT NULL COMMENT '交易结算账户id',
  `currency` varchar(32) NOT NULL COMMENT '结算货币',
  `security_id` varchar(32) DEFAULT NULL COMMENT '产品代码',
  `symbol` varchar(32) DEFAULT NULL COMMENT '产品名称',
  `position_type` varchar(45) DEFAULT NULL COMMENT '持仓类型',
  `oc_type` varchar(45) DEFAULT NULL,
  `exec_type` varchar(45) DEFAULT NULL COMMENT '成交类型，7：Taker，6：Maker',
  `side` varchar(32) DEFAULT NULL COMMENT '订单方向: 1~做多, 2~做空',
  `last_px` decimal(35,9) DEFAULT NULL COMMENT '成交价格',
  `last_qty` decimal(35,9) DEFAULT NULL COMMENT '成交数量',
  `fee` decimal(35,9) DEFAULT NULL COMMENT '手续费',
  `realized_Pnl` decimal(35,9) DEFAULT NULL COMMENT '实现盈亏',
  `rate` decimal(35,9) DEFAULT NULL,
  `Maker` int(11) DEFAULT NULL COMMENT '流动性提供者1/0',
  `update_time` varchar(30) DEFAULT NULL COMMENT '更新时间',
  `close_by` varchar(64) DEFAULT NULL COMMENT '最后操作人',
  `create_time` varchar(45) DEFAULT NULL COMMENT '创建时间',
  `location` varchar(45) DEFAULT NULL COMMENT '多实体',
  `transact_time` varchar(45) DEFAULT NULL COMMENT '业务时间',
  `info1` varchar(255) DEFAULT NULL,
  `market_indicator` varchar(45) DEFAULT NULL,
  `info2` varchar(45) DEFAULT NULL,
  `info3` varchar(45) DEFAULT NULL,
  `info4` varchar(45) DEFAULT NULL,
  `info5` varchar(45) DEFAULT NULL,
  PRIMARY KEY (`exec_id`,`user_id`) USING BTREE,
  KEY `index` (`create_time`,`security_id`,`side`,`user_id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC COMMENT='成交明细表';

CREATE TABLE `dc_orders_position` (
  `user_id` varchar(45) NOT NULL COMMENT '注册用户id',
  `security_id` varchar(30) NOT NULL COMMENT '产品代码',
  `symbol` varchar(32) DEFAULT NULL COMMENT '产品名称',
  `account_id` varchar(64) DEFAULT NULL COMMENT '交易结算账户id',
  `islp` varchar(1) DEFAULT '0',
  `currency` varchar(32) DEFAULT NULL COMMENT '结算货币',
  `status` int(11) NOT NULL COMMENT '持仓状态,0 正常，1 liq,2 禁止',
  `position_type` varchar(45) NOT NULL COMMENT '仓位模式，0：全仓，1：逐仓',
  `leverage` decimal(35,9) NOT NULL COMMENT '杠杆',
  `long_position` decimal(35,9) NOT NULL COMMENT '持仓量(多头)',
  `long_average` decimal(35,9) NOT NULL COMMENT '持仓均价(多头)',
  `long_used_margin` decimal(35,9) NOT NULL COMMENT '持仓占用保证金(多头)',
  `short_position` decimal(35,9) NOT NULL COMMENT '持仓量(空头)',
  `short_average` decimal(35,9) NOT NULL COMMENT '持仓均价(空头)',
  `short_used_margin` decimal(35,9) NOT NULL COMMENT '持仓占用保证金(空头)',
  `long_locked_position` decimal(35,9) DEFAULT NULL COMMENT '持仓锁定量(多头)',
  `short_locked_position` decimal(35,9) NOT NULL COMMENT '持仓锁定量(空头)',
  `long_liq_price` decimal(35,9) NOT NULL COMMENT '强平价格(多头)',
  `short_liq_price` decimal(35,9) NOT NULL COMMENT '强平价格(空头)',
  `update_time` varchar(30) DEFAULT NULL COMMENT '更新时间',
  `close_by` varchar(500) DEFAULT NULL COMMENT '最后操作人',
  `location` varchar(45) NOT NULL DEFAULT '' COMMENT '多实体',
  `inf1` varchar(30) DEFAULT NULL,
  `inf2` varchar(30) DEFAULT NULL,
  `inf3` varchar(30) DEFAULT NULL,
  `inf4` varchar(30) DEFAULT NULL,
  `inf5` varchar(30) DEFAULT NULL,
  `market_indicator` varchar(32) DEFAULT NULL,
  PRIMARY KEY (`location`,`user_id`,`security_id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC COMMENT='持仓汇总表';

CREATE TABLE `dc_orders_position_day` (
  `user_id` varchar(45) NOT NULL,
  `security_id` varchar(30) NOT NULL,
  `symbol` varchar(32) NOT NULL,
  `account_id` varchar(64) NOT NULL,
  `trade_date` varchar(64) NOT NULL,
  `currency` varchar(32) NOT NULL,
  `status` int(11) NOT NULL,
  `position_type` varchar(45) NOT NULL,
  `leverage` decimal(35,8) NOT NULL,
  `long_position` decimal(35,8) NOT NULL,
  `long_average` decimal(35,8) NOT NULL,
  `long_used_margin` decimal(35,8) NOT NULL,
  `short_position` decimal(35,8) NOT NULL,
  `short_average` decimal(35,8) NOT NULL,
  `short_used_margin` decimal(35,8) NOT NULL,
  `long_locked_position` decimal(35,8) DEFAULT NULL,
  `short_locked_position` decimal(35,8) NOT NULL,
  `long_liq_price` decimal(35,8) NOT NULL,
  `short_liq_price` decimal(35,8) NOT NULL,
  `update_time` varchar(30) DEFAULT NULL,
  `close_by` varchar(500) DEFAULT NULL,
  `location` varchar(45) DEFAULT NULL,
  `inf1` varchar(30) DEFAULT NULL,
  `inf2` varchar(30) DEFAULT NULL,
  `inf3` varchar(30) DEFAULT NULL,
  `inf4` varchar(30) DEFAULT NULL,
  `inf5` varchar(30) DEFAULT NULL,
  `last_price` decimal(35,9) NOT NULL,
  `market_indicator` varchar(20) NOT NULL,
  `rate_price` decimal(35,9) DEFAULT NULL,
  PRIMARY KEY (`user_id`,`security_id`,`account_id`,`trade_date`,`market_indicator`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC;

CREATE TABLE `dc_roles` (
  `id` varchar(45) NOT NULL DEFAULT '',
  `role_name` varchar(200) NOT NULL DEFAULT '',
  `terminal` varchar(45) DEFAULT NULL,
  `ip` varchar(45) DEFAULT NULL,
  `close_by` varchar(45) DEFAULT NULL,
  `remark` varchar(1000) DEFAULT NULL,
  `create_time` varchar(45) DEFAULT NULL,
  `update_time` varchar(45) DEFAULT NULL,
  `inf1` varchar(500) DEFAULT NULL,
  `inf2` varchar(500) DEFAULT NULL,
  `inf3` varchar(500) DEFAULT NULL,
  `inf4` varchar(500) DEFAULT NULL,
  `inf5` varchar(500) DEFAULT NULL,
  PRIMARY KEY (`id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `dc_roles_modules` (
  `role_id` varchar(45) NOT NULL,
  `module_id` varchar(45) NOT NULL,
  `terminal` varchar(45) DEFAULT NULL,
  `ip` varchar(45) DEFAULT NULL,
  `close_by` varchar(45) DEFAULT NULL,
  `remark` varchar(1000) DEFAULT NULL,
  `create_time` varchar(45) DEFAULT NULL,
  `update_time` varchar(45) DEFAULT NULL,
  `inf1` varchar(500) DEFAULT NULL,
  `inf2` varchar(500) DEFAULT NULL,
  `inf3` varchar(500) DEFAULT NULL,
  `inf4` varchar(500) DEFAULT NULL,
  `inf5` varchar(500) DEFAULT NULL,
  PRIMARY KEY (`role_id`,`module_id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `dc_roles_modules_action` (
  `role_id` varchar(45) NOT NULL,
  `action_id` varchar(45) NOT NULL,
  `module_id` varchar(45) NOT NULL,
  `terminal` varchar(45) DEFAULT NULL,
  `ip` varchar(45) DEFAULT NULL,
  `close_by` varchar(45) DEFAULT NULL,
  `remark` varchar(1000) DEFAULT NULL,
  `create_time` varchar(45) DEFAULT NULL,
  `update_time` varchar(45) DEFAULT NULL,
  `inf1` varchar(500) DEFAULT NULL,
  `inf2` varchar(500) DEFAULT NULL,
  `inf3` varchar(500) DEFAULT NULL,
  `inf4` varchar(500) DEFAULT NULL,
  `inf5` varchar(500) DEFAULT NULL,
  PRIMARY KEY (`role_id`,`action_id`,`module_id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `dc_symbol` (
  `id` int(45) NOT NULL,
  `symbol` varchar(45) DEFAULT NULL COMMENT '产品代码',
  `symbol_en_name` varchar(45) DEFAULT NULL COMMENT '产品英文名字',
  `symbol_cn_name` varchar(45) DEFAULT NULL COMMENT '产品中文名',
  `index_symbol` varchar(45) DEFAULT NULL COMMENT '交易对指数',
  `mark_symbol` varchar(45) DEFAULT NULL COMMENT '交易对标记价格',
  `predicate_funding_symbol` varchar(45) DEFAULT NULL COMMENT '交易对预计资金费率',
  `funding_symbol` varchar(45) DEFAULT NULL COMMENT '交易对资金费率',
  `tick_size` varchar(45) DEFAULT NULL COMMENT '价格最小变动',
  `qty_tick_size` varchar(45) DEFAULT NULL COMMENT '交易量最小变动',
  `min_order_qty` varchar(45) DEFAULT NULL COMMENT '最小下单量',
  `price_precision` int(45) DEFAULT NULL COMMENT '报价精度',
  `max_order_qty` varchar(45) DEFAULT NULL COMMENT '最大下单量',
  `min_notional` varchar(45) DEFAULT NULL COMMENT '最小名义金额',
  `market_take_bound` varchar(45) DEFAULT NULL COMMENT '市价单最大扫单偏离比例',
  `tip_order_qty` varchar(45) DEFAULT NULL COMMENT '提示交易量',
  `activity` varchar(45) DEFAULT NULL COMMENT '交易对活跃度',
  `expiried` varchar(45) DEFAULT NULL COMMENT '上下市',
  `ticker_root` varchar(45) DEFAULT NULL COMMENT '计算基准货币',
  `contract_size` varchar(45) DEFAULT NULL COMMENT '合约乘数',
  `initial_margin` varchar(45) DEFAULT NULL COMMENT '初始保证金率',
  `maint_margin` varchar(45) DEFAULT NULL COMMENT '维持保证金率',
  `funding_rate_precision` int(45) DEFAULT NULL COMMENT '资金费率',
  `funding_interval` int(45) DEFAULT NULL COMMENT '资金费率周期',
  `predicted_rate` varchar(45) DEFAULT NULL COMMENT '溢价利率',
  `adl_enable` varchar(45) DEFAULT NULL COMMENT '自动减仓功能是否开启',
  `risk_limit` varchar(45) DEFAULT NULL COMMENT '风险限额',
  `risk_step` varchar(45) DEFAULT NULL COMMENT '风险阶梯',
  `risk_tiers` json DEFAULT NULL COMMENT '名义价值风险阶梯(JSON)',
  `max_price` varchar(45) DEFAULT NULL COMMENT '价格上限',
  `taker_commission` varchar(45) DEFAULT NULL COMMENT 'taker手续费',
  `maker_commission` varchar(45) DEFAULT NULL COMMENT 'maker手续费',
  `create_time` varchar(45) DEFAULT NULL COMMENT '创建时间',
  `update_time` varchar(45) DEFAULT NULL COMMENT '更新时间',
  `close_by` varchar(45) DEFAULT NULL COMMENT '最后操作人',
  `volume_precision` int(45) DEFAULT NULL COMMENT '链上报价量精度',
  `base_currency` varchar(45) DEFAULT NULL COMMENT '基准货币',
  `quote_currency` varchar(45) DEFAULT NULL COMMENT '报价货币',
  `qty_precision` int(45) DEFAULT NULL COMMENT '报价量精度',
  `value_precision` int(45) DEFAULT NULL COMMENT '价值精度',
  `assets` varchar(45) DEFAULT NULL COMMENT '资产类别',
  PRIMARY KEY (`id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='产品表';

-- Keep a fresh standalone installation immediately tradeable. AdminSvr
-- publishes this catalog to TradeSvr; without a row every order is rejected
-- with SYMBOL_NOTEXIST.
INSERT INTO `dc_symbol` (`id`,`symbol`,`symbol_en_name`,`symbol_cn_name`,`index_symbol`,`mark_symbol`,`predicate_funding_symbol`,`funding_symbol`,`tick_size`,`qty_tick_size`,`min_order_qty`,`price_precision`,`max_order_qty`,`min_notional`,`market_take_bound`,`tip_order_qty`,`activity`,`expiried`,`ticker_root`,`contract_size`,`initial_margin`,`maint_margin`,`funding_rate_precision`,`funding_interval`,`predicted_rate`,`adl_enable`,`risk_limit`,`risk_step`,`max_price`,`taker_commission`,`maker_commission`,`create_time`,`update_time`,`close_by`,`volume_precision`,`base_currency`,`quote_currency`,`qty_precision`,`value_precision`,`assets`) VALUES
  (1,'BTCUSDT','BTCUSDT','BTC/USDT','.BTCUSDT','.BTCUSDTMP','.BTCUSDTPREDFR','.BTCUSDTFR','0.10000000','0.00010000','0.00010000',1,'10.00000000','5.00000000','0.05','2.00000000','1','0','USDT','1','0.01000000','0.00500000',8,28800,'','1','','9',' ','0.00060000','0.00020000','2023-01-03 14:31:00','2023-01-03 14:31:00','system',4,'BTC','USDT',4,4,NULL);

CREATE TABLE `dc_symbol_category` (
  `id` int(11) NOT NULL,
  `symbol_category` varchar(45) DEFAULT NULL COMMENT '产品分类',
  `level` int(11) DEFAULT NULL COMMENT '产品分类',
  `sort` int(11) DEFAULT NULL,
  `parent_symbol_category` varchar(45) DEFAULT NULL COMMENT '关联产品分类',
  `create_time` varchar(45) DEFAULT NULL COMMENT '创建时间',
  `update_time` varchar(45) DEFAULT NULL COMMENT '更新时间',
  `close_by` varchar(45) DEFAULT NULL COMMENT '最后操作人',
  `location` varchar(45) DEFAULT NULL COMMENT '多实体',
  `scale` int(11) DEFAULT '9',
  `trade_currency` varchar(45) DEFAULT NULL,
  `lp_currency` varchar(45) DEFAULT NULL,
  `inf1` varchar(45) DEFAULT NULL,
  `inf2` varchar(45) DEFAULT NULL,
  `alias` varchar(45) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC COMMENT='产品分类表';

CREATE TABLE `dc_system_message` (
  `id` varchar(255) NOT NULL COMMENT 'ID序列号',
  `user_id` varchar(45) DEFAULT NULL COMMENT '用户名称',
  `type` varchar(45) DEFAULT NULL COMMENT '类型',
  `read_flag` longblob COMMENT '读标记',
  `del_flag` varchar(45) DEFAULT '0' COMMENT '删除标记',
  `content` varchar(13000) DEFAULT NULL COMMENT '内容',
  `closeby` varchar(45) DEFAULT NULL COMMENT '操作人',
  `create_time` varchar(45) DEFAULT NULL COMMENT '创建时间',
  `update_time` varchar(45) DEFAULT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`) USING BTREE,
  KEY `updatetime` (`update_time`,`user_id`,`id`,`del_flag`,`type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC COMMENT='系统消息';

CREATE TABLE `dc_system_parameter` (
  `param_key` varchar(45) NOT NULL COMMENT '参数key',
  `user_id` varchar(45) NOT NULL COMMENT '用户名',
  `param_value` varchar(15000) DEFAULT NULL COMMENT '参数值',
  `param_desc` varchar(45) DEFAULT NULL COMMENT '描述',
  `create_time` varchar(45) DEFAULT NULL COMMENT '创建时间',
  `update_time` varchar(45) DEFAULT NULL COMMENT '更新时间',
  PRIMARY KEY (`param_key`,`user_id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC COMMENT='系统参数表';

CREATE TABLE `dc_user_role` (
  `user_id` varchar(100) NOT NULL,
  `role_id` varchar(100) NOT NULL,
  `user_name` varchar(255) DEFAULT NULL,
  `role_name` varchar(255) DEFAULT NULL,
  `close_by` varchar(45) DEFAULT NULL,
  `create_time` varchar(45) DEFAULT NULL,
  `update_time` varchar(45) DEFAULT NULL,
  `inf1` varchar(500) DEFAULT NULL,
  `inf2` varchar(500) DEFAULT NULL,
  `inf3` varchar(500) DEFAULT NULL,
  `inf4` varchar(500) DEFAULT NULL,
  `inf5` varchar(500) DEFAULT NULL,
  PRIMARY KEY (`user_id`,`role_id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `dc_users` (
  `user_id` varchar(64) NOT NULL COMMENT '用户id',
  `user_name` varchar(255) NOT NULL DEFAULT '' COMMENT '登录名',
  `name` varchar(64) DEFAULT NULL COMMENT '用户名',
  `password` varchar(64) DEFAULT NULL COMMENT '密码',
  `mail` varchar(255) DEFAULT NULL COMMENT '邮箱',
  `user_type` varchar(45) DEFAULT NULL COMMENT '用户类型',
  `enable` char(1) DEFAULT NULL COMMENT '启用',
  `remark` varchar(1000) DEFAULT NULL COMMENT '备注',
  `create_time` varchar(45) DEFAULT NULL COMMENT '创建时间',
  `update_time` varchar(45) DEFAULT NULL COMMENT '更新时间',
  `mac` varchar(45) DEFAULT NULL COMMENT '主mac地址',
  `mac1` varchar(45) DEFAULT NULL COMMENT '备用mac地址1',
  `mac2` varchar(45) DEFAULT NULL COMMENT '备用mac地址2',
  `inf1` varchar(1000) DEFAULT NULL COMMENT '扩展字段1',
  `inf2` varchar(1000) DEFAULT NULL COMMENT '扩展字段2',
  `inf3` varchar(1000) DEFAULT NULL COMMENT '扩展字段3',
  `inf4` varchar(1000) DEFAULT NULL COMMENT '扩展字段4',
  `inf5` varchar(1000) DEFAULT NULL COMMENT '扩展字段5',
  `enable_trade` varchar(1) DEFAULT NULL COMMENT '是否能交易',
  `enable_cash_in` varchar(1) DEFAULT NULL COMMENT '是否能充值',
  `enable_cash_out` varchar(1) DEFAULT NULL COMMENT '是否能提现',
  `referrer` varchar(45) DEFAULT NULL COMMENT '推荐人',
  `close_by` varchar(45) DEFAULT NULL COMMENT '操作人',
  `location` varchar(64) NOT NULL DEFAULT '0' COMMENT '多实体',
  PRIMARY KEY (`location`,`user_name`) USING BTREE,
  UNIQUE KEY `uq_users_location_user_id` (`location`,`user_id`) USING BTREE,
  KEY `idx_users_user_name` (`user_name`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8 ROW_FORMAT=DYNAMIC COMMENT='用户表';

CREATE TABLE `dc_users_api` (
  `user_id` varchar(45) NOT NULL COMMENT '用户id',
  `type` varchar(45) NOT NULL COMMENT '类型',
  `api_key` varchar(255) NOT NULL DEFAULT '' COMMENT 'api key',
  `secret_key` varchar(64) DEFAULT NULL COMMENT 'SECRET_KEY',
  `enable` char(1) DEFAULT NULL COMMENT '启用',
  `create_time` varchar(45) DEFAULT NULL COMMENT '创建时间',
  `update_time` varchar(45) DEFAULT NULL COMMENT '更新时间',
  `close_by` varchar(45) DEFAULT NULL COMMENT '操作人',
  `inf1` varchar(45) DEFAULT NULL COMMENT '扩展字段',
  `location` varchar(64) NOT NULL DEFAULT '' COMMENT '多实体',
  PRIMARY KEY (`api_key`,`user_id`,`type`) USING BTREE,
  KEY `idx_users_api_location_user` (`location`,`user_id`,`enable`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8 ROW_FORMAT=DYNAMIC COMMENT='api用户表';

CREATE TABLE `dc_users_balance` (
  `user_id` varchar(45) NOT NULL COMMENT '注册用户id',
  `account_id` varchar(64) DEFAULT NULL COMMENT '交易结算账户id',
  `currency` varchar(32) DEFAULT NULL COMMENT '结算货币',
  `balance` decimal(30,16) DEFAULT NULL COMMENT '总余额',
  `used_margin` decimal(30,16) DEFAULT NULL COMMENT '占用保证金',
  `freezed_margin` decimal(30,16) DEFAULT NULL COMMENT '冻结金额',
  `freezed_commission` decimal(30,16) DEFAULT NULL COMMENT '冻结手续费',
  `update_time` varchar(30) DEFAULT NULL COMMENT '更新时间',
  `close_by` varchar(600) DEFAULT NULL COMMENT '最后操作人',
  `location` varchar(30) NOT NULL DEFAULT '' COMMENT '多实体',
  `is_trader` varchar(2) DEFAULT NULL COMMENT 'trade，lp',
  `position_type` varchar(2) DEFAULT NULL COMMENT '逐仓，全仓标记',
  `security_id` varchar(45) DEFAULT NULL COMMENT 'market_index',
  `market_indicator` varchar(20) DEFAULT NULL,
  PRIMARY KEY (`location`,`user_id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC COMMENT='用户资金表';

CREATE TABLE `dc_users_balance_day` (
  `user_id` varchar(45) NOT NULL,
  `account_id` varchar(64) NOT NULL,
  `trade_date` varchar(64) NOT NULL,
  `currency` varchar(32) NOT NULL,
  `balance` decimal(30,16) DEFAULT NULL,
  `used_margin` decimal(30,16) DEFAULT NULL,
  `freezed_margin` decimal(30,16) DEFAULT NULL,
  `freezed_commission` decimal(30,16) DEFAULT NULL,
  `update_time` varchar(30) DEFAULT NULL,
  `close_by` varchar(600) DEFAULT NULL,
  `location` varchar(30) DEFAULT NULL,
  `is_trader` varchar(2) DEFAULT NULL,
  `position_type` varchar(2) DEFAULT NULL,
  `security_id` varchar(45) DEFAULT NULL,
  `market_indicator` varchar(20) NOT NULL,
  PRIMARY KEY (`user_id`,`account_id`,`trade_date`,`market_indicator`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC;

CREATE TABLE `dc_users_cash_log` (
  `id` varchar(300) NOT NULL COMMENT '自增长id',
  `user_id` varchar(64) NOT NULL COMMENT '注册用户id',
  `account_id` varchar(255) NOT NULL COMMENT '交易结算账户id',
  `address` varchar(255) DEFAULT NULL COMMENT '地址',
  `txid` varchar(255) NOT NULL COMMENT '交易id',
  `transaction_hash` varchar(500) DEFAULT NULL COMMENT '出金hash',
  `confirm_num` int(11) DEFAULT NULL COMMENT '链上确认次数',
  `currency` varchar(32) DEFAULT NULL COMMENT '结算货币',
  `amount` decimal(30,16) DEFAULT NULL COMMENT '金额',
  `status` int(11) DEFAULT NULL COMMENT '状态，0：处理中，1：成功，2：失败，3：发出',
  `side` int(11) DEFAULT NULL COMMENT '方向：0：充值，1：提现',
  `cash_type` varchar(1) DEFAULT NULL COMMENT '出入金类型，1：C端，2：KOL提佣',
  `nonce` int(11) DEFAULT NULL COMMENT '提现交易编号',
  `fee_type` varchar(255) DEFAULT NULL COMMENT '费用类型:0固定，1百分比',
  `fee_value` varchar(255) DEFAULT NULL COMMENT '费用值',
  `fee_amount` decimal(30,16) DEFAULT NULL COMMENT '费用金额',
  `msg` varchar(45) DEFAULT NULL COMMENT '消息',
  `remark` varchar(45) DEFAULT NULL COMMENT '备注信息',
  `create_time` varchar(45) DEFAULT NULL COMMENT '创建时间',
  `update_time` varchar(30) DEFAULT NULL COMMENT '更新时间',
  `close_by` varchar(30) DEFAULT NULL COMMENT '最后操作人',
  `location` varchar(45) DEFAULT NULL COMMENT '多实体',
  `market_indicator` varchar(45) DEFAULT NULL,
  PRIMARY KEY (`id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC COMMENT='充值提现表';

CREATE TABLE `dc_users_config` (
  `user_id` varchar(45) NOT NULL COMMENT '注册用户id',
  `position_way_type` varchar(32) DEFAULT NULL COMMENT '持仓方式',
  `taker_commission` decimal(30,16) DEFAULT NULL COMMENT 'taker手续费',
  `maker_commission` decimal(30,16) DEFAULT NULL COMMENT 'maker手续费',
  `update_time` varchar(30) DEFAULT NULL COMMENT '更新时间',
  `close_by` varchar(600) DEFAULT NULL COMMENT '最后操作人',
  `location` varchar(30) NOT NULL DEFAULT '' COMMENT '多实体',
  `market_indicator` varchar(20) DEFAULT NULL,
  PRIMARY KEY (`location`,`user_id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC COMMENT='用户配置表';

CREATE TABLE `dc_users_posting` (
  `id` varchar(255) NOT NULL COMMENT '自增长id',
  `user_id` varchar(45) NOT NULL COMMENT '注册用户id',
  `security_id` varchar(30) DEFAULT NULL COMMENT '产品代码',
  `symbol` varchar(32) DEFAULT NULL COMMENT '产品名称',
  `account_id` varchar(64) DEFAULT NULL COMMENT '交易结算账户id',
  `currency` varchar(32) DEFAULT NULL COMMENT '结算货币',
  `type` int(11) NOT NULL COMMENT '类型,1：充值，2：提现，3：手续费，4：资金费，5：盈亏，6：赠金发放，7：赠金销毁，8：返佣',
  `amount` varchar(45) NOT NULL COMMENT '金额',
  `source` varchar(45) DEFAULT NULL COMMENT '来源',
  `source_id` varchar(128) DEFAULT NULL COMMENT '来源id',
  `remark` varchar(45) DEFAULT NULL COMMENT '备注信息',
  `create_time` varchar(35) DEFAULT NULL COMMENT '创建时间',
  `update_time` varchar(30) DEFAULT NULL COMMENT '更新时间',
  `close_by` varchar(500) DEFAULT NULL COMMENT '最后操作人',
  `location` varchar(45) DEFAULT NULL COMMENT '多实体',
  `market_indicator` varchar(45) DEFAULT NULL,
  PRIMARY KEY (`id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC COMMENT='资金流水表';

CREATE TABLE `dc_users_session` (
  `token` varchar(90) NOT NULL COMMENT '会话编号',
  `user_id` varchar(64) DEFAULT NULL COMMENT '登录名',
  `name` varchar(90) DEFAULT NULL COMMENT '用户名',
  `ip` varchar(45) DEFAULT NULL COMMENT 'ip',
  `create_time` varchar(30) DEFAULT NULL COMMENT '创建时间',
  `client_type` varchar(45) DEFAULT NULL COMMENT '登录类型',
  `infs` varchar(8000) DEFAULT NULL COMMENT '扩展信息',
  `location` varchar(45) DEFAULT NULL COMMENT '多实体',
  PRIMARY KEY (`token`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC COMMENT='用户会话控制表';

CREATE TABLE `dc_users_symbol_config` (
  `user_id` varchar(45) NOT NULL COMMENT '注册用户id',
  `security_id` varchar(30) NOT NULL COMMENT '产品代码',
  `symbol` varchar(32) DEFAULT NULL COMMENT '产品名称',
  `leverage` int(11) DEFAULT '1' COMMENT '杠杆',
  `position_type` varchar(30) DEFAULT NULL COMMENT '逐仓，全仓标记',
  `update_time` varchar(30) DEFAULT NULL COMMENT '更新时间',
  `close_by` varchar(600) DEFAULT NULL COMMENT '最后操作人',
  `location` varchar(30) NOT NULL DEFAULT '' COMMENT '多实体',
  `market_indicator` varchar(20) DEFAULT NULL,
  PRIMARY KEY (`location`,`user_id`,`security_id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC COMMENT='用户配置表';
