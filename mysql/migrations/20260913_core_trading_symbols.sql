-- Add the first three post-BTC perpetual products to the global catalog.
-- Idempotent because deploy-saas.sh reapplies every migration on each deploy.
-- Exchange filters were verified through the production APSSvr BNFutures
-- exchangeInfo adapter on 2026-09-13. Tenant enablement and Robot definitions
-- remain separate control-plane operations.

SET @next_symbol_id = (SELECT COALESCE(MAX(id), 0) + 1 FROM dc_symbol);
INSERT INTO dc_symbol
  (id,symbol,symbol_en_name,symbol_cn_name,index_symbol,mark_symbol,predicate_funding_symbol,funding_symbol,
   tick_size,qty_tick_size,min_order_qty,price_precision,max_order_qty,min_notional,market_take_bound,
   tip_order_qty,activity,expiried,ticker_root,contract_size,initial_margin,maint_margin,funding_rate_precision,
   funding_interval,predicted_rate,adl_enable,risk_limit,risk_step,max_price,taker_commission,maker_commission,
   create_time,update_time,close_by,volume_precision,base_currency,quote_currency,qty_precision,value_precision,assets)
SELECT @next_symbol_id,'ETHUSDT','ETHUSDT','ETH/USDT','.ETHUSDT','.ETHUSDTMP','.ETHUSDTPREDFR','.ETHUSDTFR',
       '0.01000000','0.00100000','0.00100000',2,'10000.00000000','5.00000000','0.05','0.10000000',
       '1','0','USDT','1','0.01000000','0.00500000',8,28800,'','1','','9','306177',
       '0.00060000','0.00020000','2026-09-13 00:00:00','2026-09-13 00:00:00','system',3,'ETH','USDT',3,4,NULL
WHERE NOT EXISTS (SELECT 1 FROM dc_symbol WHERE symbol='ETHUSDT');

SET @next_symbol_id = (SELECT COALESCE(MAX(id), 0) + 1 FROM dc_symbol);
INSERT INTO dc_symbol
  (id,symbol,symbol_en_name,symbol_cn_name,index_symbol,mark_symbol,predicate_funding_symbol,funding_symbol,
   tick_size,qty_tick_size,min_order_qty,price_precision,max_order_qty,min_notional,market_take_bound,
   tip_order_qty,activity,expiried,ticker_root,contract_size,initial_margin,maint_margin,funding_rate_precision,
   funding_interval,predicted_rate,adl_enable,risk_limit,risk_step,max_price,taker_commission,maker_commission,
   create_time,update_time,close_by,volume_precision,base_currency,quote_currency,qty_precision,value_precision,assets)
SELECT @next_symbol_id,'SOLUSDT','SOLUSDT','SOL/USDT','.SOLUSDT','.SOLUSDTMP','.SOLUSDTPREDFR','.SOLUSDTFR',
       '0.01000000','0.01000000','0.01000000',2,'1000000.00000000','5.00000000','0.05','1.00000000',
       '1','0','USDT','1','0.01000000','0.00500000',8,28800,'','1','','9','6857',
       '0.00060000','0.00020000','2026-09-13 00:00:00','2026-09-13 00:00:00','system',2,'SOL','USDT',2,4,NULL
WHERE NOT EXISTS (SELECT 1 FROM dc_symbol WHERE symbol='SOLUSDT');

SET @next_symbol_id = (SELECT COALESCE(MAX(id), 0) + 1 FROM dc_symbol);
INSERT INTO dc_symbol
  (id,symbol,symbol_en_name,symbol_cn_name,index_symbol,mark_symbol,predicate_funding_symbol,funding_symbol,
   tick_size,qty_tick_size,min_order_qty,price_precision,max_order_qty,min_notional,market_take_bound,
   tip_order_qty,activity,expiried,ticker_root,contract_size,initial_margin,maint_margin,funding_rate_precision,
   funding_interval,predicted_rate,adl_enable,risk_limit,risk_step,max_price,taker_commission,maker_commission,
   create_time,update_time,close_by,volume_precision,base_currency,quote_currency,qty_precision,value_precision,assets)
SELECT @next_symbol_id,'UNIUSDT','UNIUSDT','UNI/USDT','.UNIUSDT','.UNIUSDTMP','.UNIUSDTPREDFR','.UNIUSDTFR',
       '0.00100000','1.00000000','1.00000000',3,'2000000.00000000','5.00000000','0.05','10.00000000',
       '1','0','USDT','1','0.01000000','0.00500000',8,28800,'','1','','9','2684',
       '0.00060000','0.00020000','2026-09-13 00:00:00','2026-09-13 00:00:00','system',0,'UNI','USDT',0,4,NULL
WHERE NOT EXISTS (SELECT 1 FROM dc_symbol WHERE symbol='UNIUSDT');

-- Align existing rows without changing their ids. Robot and tenant enablement
-- are intentionally not performed here.
UPDATE dc_symbol SET tick_size='0.01000000',qty_tick_size='0.00100000',min_order_qty='0.00100000',
  price_precision=2,max_order_qty='10000.00000000',min_notional='5.00000000',market_take_bound='0.05',
  max_price='306177',volume_precision=3,base_currency='ETH',quote_currency='USDT',qty_precision=3,
  value_precision=4,update_time='2026-09-13 00:00:00',close_by='system' WHERE symbol='ETHUSDT';
UPDATE dc_symbol SET tick_size='0.01000000',qty_tick_size='0.01000000',min_order_qty='0.01000000',
  price_precision=2,max_order_qty='1000000.00000000',min_notional='5.00000000',market_take_bound='0.05',
  max_price='6857',volume_precision=2,base_currency='SOL',quote_currency='USDT',qty_precision=2,
  value_precision=4,update_time='2026-09-13 00:00:00',close_by='system' WHERE symbol='SOLUSDT';
UPDATE dc_symbol SET tick_size='0.00100000',qty_tick_size='1.00000000',min_order_qty='1.00000000',
  price_precision=3,max_order_qty='2000000.00000000',min_notional='5.00000000',market_take_bound='0.05',
  max_price='2684',volume_precision=0,base_currency='UNI',quote_currency='USDT',qty_precision=0,
  value_precision=4,update_time='2026-09-13 00:00:00',close_by='system' WHERE symbol='UNIUSDT';
