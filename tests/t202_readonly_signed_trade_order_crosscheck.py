#!/usr/bin/env python3
"""Read-only original A/B signed Trade OPEN_ORDER vs Order Maker crosscheck.
Complements T199ReadOnlyLiveWalQuorumProof (that authenticates RSA custody).
No gateway requests, client writes, key generation or WAL modifications."""
import base64
import hashlib
import json
import struct
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

BASE=Path('/Users/kong/.opentradingcore/dc-saas-runtime-clean-20261016/data/common-t182-ready')
def certified_paired_frames(service,partition):
    roots=[BASE/service/(service+n)/service/(service+n)/partition/'epoch-2/business.wal'
           for n in ('A','B')]
    a,b=[p.read_bytes() for p in roots]
    assert a and a==b, f'{service} physical A/B divergent'
    offset=0; index=0
    while offset<len(a):
        header=a[offset:offset+28]
        assert len(header)==28
        magic,epoch,seq,size,crc=struct.unpack('>iqqii',header)
        assert magic==0x43425731 and epoch==2 and seq==index+1 and 0<size<1_000_000
        offset+=28
        encoded=a[offset:offset+size].decode('utf-8')
        offset+=size;index+=1
        row=encoded.split('\t')
        assert len(row)==7
        decode=lambda value:base64.b64decode(value,validate=True).decode('utf-8')
        assert decode(row[0])==partition and int(row[1])==2 and int(row[2])==seq
        yield seq,decode(row[3]),json.loads(decode(row[6]))
    assert offset==len(a)
def dec(v):return Decimal(str(v))
order={}
for seq,event,mutation in certified_paired_frames('OrderSvr','P089'):
    assert event.startswith('STATE_')
    id=mutation.get('orderId')
    assert id
    if mutation.get('operation')=='REMOVE':order.pop(id,None)
    else:order[id]=(seq,mutation['order'])
trade={}
frozen={}
receipts=set()
for seq,event,batch in certified_paired_frames('TradeSvr','P246'):
    assert event=='STATE_BATCH'
    for m in batch['mutations']:
        t=m['entityType'];op=m['operation']
        if t=='OPEN_ORDER':
            if op=='UPSERT':
                report=json.loads(m['payload'])
                identity=report['OrderID']
                assert identity not in trade
                trade[identity]=(seq,report)
            else:
                id=m['entityKey'].split('\x1f')[-1];trade.pop(id,None)
        if t=='POSITION' and op=='UPSERT':
            val=json.loads(m['payload'])
            frozen[(val['location'],val['userID'],val['securityID'])]=val
        if t=='DEDUPE_RESULT':
            receipt=json.loads(m['payload'])
            assert receipt['executionKey'] not in receipts
            receipts.add(receipt['executionKey'])
assert len(trade)==4, f'expected 4 signed open orders, got {len(trade)}'
assert len(receipts)==4
quantity=defaultdict(Decimal);notional=defaultdict(Decimal)
for id,(trade_seq,report) in trade.items():
    assert id in order, f'signed Trade open {trade_seq} missing in signed Order current'
    order_seq,book=order[id]
    assert book['orderStatus']=='New' and book['maker'] is True
    keys=(('Location','location'),('UserID','userId'),
          ('SecurityID','securityId'),('MarketIndicator','marketIndicator'),
          ('Side','side'),('Demo','demo'))
    for tkey,okey in keys:
        assert str(report[tkey]).lower()==str(book[okey]).lower(),f'{tkey} mismatch for signed seq {trade_seq}'
    assert dec(report['Price'])==dec(book['price'])
    assert dec(report['OrderQty'])==dec(book['qty'])
    k=(report['Location'],report['UserID'],report['SecurityID'])
    quantity[k]+=dec(report['OrderQty'])
    notional[k]+=dec(report['OrderQty'])*dec(report['Price'])
for k,total_qty in quantity.items():
    assert k in frozen
    pos=frozen[k]
    assert dec(pos['freezed'])>=total_qty, 'Trade original position frozen quantity less than open orders'
    assert dec(pos['freezedVolume'])>=notional[k], 'Trade frozen notional less than current open orders'
print('T202_SIGNED_TRADE_ORDER_ORIGINAL_IDENTITY_PASS',
      'order_p089_current='+str(len(order)),
      'trade_p246_signed_open='+str(len(trade)),
      'same_tenant_user_product_price_qty_side_demo=4/4',
      'signed_frozen_qty_and_notional_cover=4/4',
      'AB_physical_bytes_identical=true')

# Detect, but NEVER auto-correct, an already physically signed financial
# disagreement. An authenticated WAL is a historical fact, not permission
# to mutate the user's balance in MySQL or create fake reserve certificates.
latest_balance=None
latest_position=None
for seq,event,batch in certified_paired_frames('TradeSvr','P246'):
    for mut in batch['mutations']:
        if mut['operation']!='UPSERT':continue
        if mut['entityType']=='ACCOUNT_BALANCE':
            row=json.loads(mut['payload'])
            if row.get('location')=='R0F6CC' and row.get('userID')=='robotmaker':
                latest_balance=row
        elif mut['entityType']=='POSITION':
            row=json.loads(mut['payload'])
            if row.get('location')=='R0F6CC' and row.get('userID')=='robotmaker' and row.get('securityID')=='BTCUSDT':
                latest_position=row
assert latest_balance is not None and latest_position is not None
gap=dec(latest_position['freezedMargin'])-dec(latest_balance['freezedMargin'])
commission_gap=dec(latest_position['freezedCommission'])-dec(latest_balance['freezedCommission'])
assert gap>0 and commission_gap>0, 'T204 previous signed reserve gap changed: re-evaluate this baseline'
print('T204_SIGNED_HISTORICAL_RESERVE_GAP_NO_GO',
      'position_frozen_margin='+str(latest_position['freezedMargin']),
      'account_frozen_margin='+str(latest_balance['freezedMargin']),
      'margin_undercoverage='+str(gap),
      'commission_undercoverage='+str(commission_gap),
      'no_automated_repair_or_release=true')
