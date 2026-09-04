-- DC SaaS perpetual risk transfer schema
-- Apply before deploying TradeSvr/LiqSvr bankruptcy + ADL runtime code.
-- Designed for MySQL/InnoDB. DDL is idempotent for fresh environments.

CREATE TABLE IF NOT EXISTS dc_insurance_fund (
    location          VARCHAR(64)  NOT NULL,
    security_id       VARCHAR(64)  NOT NULL,
    balance           DECIMAL(36,18) NOT NULL DEFAULT 0,
    update_time       DATETIME(3)  NOT NULL,
    PRIMARY KEY (location, security_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS dc_insurance_position (
    location          VARCHAR(64)  NOT NULL,
    security_id       VARCHAR(64)  NOT NULL,
    position_side     VARCHAR(8)   NOT NULL,
    quantity          DECIMAL(36,18) NOT NULL DEFAULT 0,
    average_price     DECIMAL(36,18) NOT NULL DEFAULT 0,
    reserved_notional DECIMAL(36,18) NOT NULL DEFAULT 0,
    update_time       DATETIME(3)  NOT NULL,
    PRIMARY KEY (location, security_id, position_side),
    KEY idx_insurance_position_market (location, security_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS dc_bankruptcy_transfer (
    location              VARCHAR(64)   NOT NULL,
    liquidation_order_id  VARCHAR(128)  NOT NULL,
    liquidation_side      VARCHAR(8)    NOT NULL,
    user_id               VARCHAR(128)  NOT NULL,
    security_id           VARCHAR(64)   NOT NULL,
    bankruptcy_price      DECIMAL(36,18) NOT NULL,
    requested_quantity    DECIMAL(36,18) NOT NULL DEFAULT 0,
    insurance_quantity    DECIMAL(36,18) NOT NULL DEFAULT 0,
    adl_quantity          DECIMAL(36,18) NOT NULL DEFAULT 0,
    insurance_notional    DECIMAL(36,18) NOT NULL DEFAULT 0,
    settlement_pnl        DECIMAL(36,18) NOT NULL DEFAULT 0,
    balance_after         DECIMAL(36,18) NOT NULL DEFAULT 0,
    used_margin_after     DECIMAL(36,18) NOT NULL DEFAULT 0,
    status                VARCHAR(32)   NOT NULL,
    create_time           DATETIME(3)   NOT NULL,
    update_time           DATETIME(3)   NOT NULL,
    completed_time        DATETIME(3)   NULL,
    PRIMARY KEY (location, liquidation_order_id, liquidation_side),
    KEY idx_bankruptcy_market_status (location, security_id, status),
    KEY idx_bankruptcy_user (location, user_id, security_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS dc_adl_execution_v2 (
    location                 VARCHAR(64)   NOT NULL,
    adl_execution_id         VARCHAR(128)  NOT NULL,
    liquidation_order_id     VARCHAR(128)  NOT NULL,
    rank_no                  INT           NOT NULL,
    liquidated_user_id       VARCHAR(128)  NOT NULL,
    candidate_user_id        VARCHAR(128)  NOT NULL,
    security_id              VARCHAR(64)   NOT NULL,
    bankrupt_side            VARCHAR(8)    NOT NULL,
    candidate_position_side  VARCHAR(8)    NOT NULL,
    execution_price          DECIMAL(36,18) NOT NULL,
    quantity                 DECIMAL(36,18) NOT NULL,
    profit_rate              DECIMAL(36,18) NOT NULL DEFAULT 0,
    effective_leverage       DECIMAL(36,18) NOT NULL DEFAULT 0,
    realized_pnl             DECIMAL(36,18) NOT NULL DEFAULT 0,
    released_margin          DECIMAL(36,18) NOT NULL DEFAULT 0,
    position_before          DECIMAL(36,18) NOT NULL DEFAULT 0,
    position_after           DECIMAL(36,18) NOT NULL DEFAULT 0,
    balance_before           DECIMAL(36,18) NOT NULL DEFAULT 0,
    balance_after            DECIMAL(36,18) NOT NULL DEFAULT 0,
    create_time              DATETIME(3)   NOT NULL,
    PRIMARY KEY (location, adl_execution_id),
    KEY idx_adl_liquidation (location, liquidation_order_id),
    KEY idx_adl_candidate (location, candidate_user_id, security_id),
    KEY idx_adl_market_time (location, security_id, create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
