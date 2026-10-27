#!/usr/bin/env python3
"""Read-only cash projection audit. MUST be paired with T190ReadOnlyWalProof RSA cert validation.
No financial mutation, WAL rewrite, recovery lease or signature generation."""
import base64,hashlib,json,struct,subprocess,sys
from pathlib import Path
from decimal import Decimal
root=Path('/Users/kong/.opentradingcore/dc-saas-runtime-clean-20261016/data/common-t182-ready/TradeSvr')
paths=[root/n/'TradeSvr'/n/'P246/epoch-2/business.wal' for n in ('TradeSvrA','TradeSvrB')]
data=[p.read_bytes() for p in paths]
assert data[0]==data[1], 'original A/B WAL diverged'
# The original three CashIn commits stay prefix-immutable, but real Order
# risk admission rightly appends later NEWING batches to this same WAL.
# Current whole-head RSA custody must be checked separately by Common.
original_first_three_sha='8d3f4bf62245669ff627e9d14f75a00a636e92e3671ebc7fdf896e7f53bb58b5'
payload=data[1]; offset=0;events=[];total=0
while offset<len(payload):
    magic,epoch,seq,size,crc=struct.unpack_from('>iqqii',payload,offset);offset+=28
    assert magic==0x43425731 and epoch==2 and seq==total+1
    total+=1
    frame=payload[offset:offset+size];offset+=size
    fields=frame.decode('utf-8').split('\t')
    assert len(fields)==7
    decode=lambda x:base64.b64decode(x,validate=True).decode('utf-8')
    assert decode(fields[0])=='P246' and int(fields[1])==2 and int(fields[2])==seq
    assert decode(fields[3])=='STATE_BATCH'
    batch=json.loads(decode(fields[6]))
    if seq>3:
        assert batch['location']=='R0F6CC' and batch['sourceType']!='CASH_IN', 'new cash mutation after original audited first three'
        continue
    assert batch['sourceType']=='CASH_IN' and len(batch['mutations'])==2 and batch['location']=='R0F6CC'
    if seq==3:
        assert hashlib.sha256(payload[:offset]).hexdigest()==original_first_three_sha, 'original three certified CashIn frames changed'
    ab,posting=[json.loads(m['payload']) for m in batch['mutations']]
    assert {m['entityType'] for m in batch['mutations']}=={'ACCOUNT_BALANCE','POSTING'}
    req=batch['requestId']
    stable='E2CASH-'+hashlib.sha256(('\x1f'.join(('OTC_TRADE_CERTIFIED_CASH_IN_V1',batch['location'],posting['userID'],req))).encode()).hexdigest()
    assert posting['ID']==stable and posting['sourceID']==req
    assert posting['userID']==ab['userID'] and posting['location']==ab['location'] and posting['type']=='1'
    events.append((stable,posting['location'],posting['userID'],posting['type'],Decimal(posting['amount']),req,Decimal(ab['balance'])))
assert len(events)==3 and len({x[0] for x in events})==3 and total>=3
sql='SELECT id,location,user_id,type,amount,source_id FROM dc_users_posting WHERE id LIKE "E2CASH-%" AND location="R0F6CC";SELECT location,user_id,balance FROM dc_users_balance WHERE location="R0F6CC";'
cmd=['docker','exec','-i','dc-saas-mysql','sh','-lc','mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N dc -e '+repr(sql)]
p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,check=True,text=True)
rows=[line.split('\t') for line in p.stdout.strip().splitlines()]
postings={(r[0],r[1],r[2],r[3],Decimal(r[4]),r[5]) for r in rows if len(r)==6}
balances={(r[0],r[1]):Decimal(r[2]) for r in rows if len(r)==3}
assert len(postings)==3, 'physical posted amounts/dedup must exactly match WAL'
for stable,loc,user,typ,amount,req,after in events:
    assert (stable,loc,user,typ,amount,req) in postings
    assert balances[(loc,user)]==after
print('T190_E2_READONLY_CASH_PROJECTION_PASS wal_hash_identical=true signed_quorum_precondition=separate original_cash_commits=3 postings=3 exact_balances=3 current_total_wal_frames='+str(total))
