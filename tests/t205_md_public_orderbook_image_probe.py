#!/usr/bin/env python3
"""Read-only: query actual Gateway MDSvr public orderbook three times.
No token, trade, account mutation or server-side admin route required."""
import argparse
import json
import os
import time
import urllib.request
from decimal import Decimal

parser=argparse.ArgumentParser()
parser.add_argument('--gateway',default='http://127.0.0.1:'+os.environ.get('WEB_LISTEN_PORT','')+'/httpapi/')
parser.add_argument('--location',default='R0F6CC')
parser.add_argument('--security-id',default='BTCUSDT')
parser.add_argument('--samples',type=int,default=3)
parser.add_argument('--interval',type=float,default=2)
args=parser.parse_args()
assert args.gateway.startswith('http://127.0.0.1:') or args.gateway.startswith('http://localhost:')
assert 1<=args.samples<=12 and 0<=args.interval<=5
request=json.dumps({'serverName':'MDSvr','method':'queryPublicMarket',
    'content':{'location':args.location,'securityID':args.security_id}}).encode('utf-8')
seen=[]
for i in range(args.samples):
    req=urllib.request.Request(args.gateway,data=request,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=12) as response:
        d=json.load(response)
    assert d.get('code')==0,d.get('msg')
    book=d['data']['orderBook']
    assert book['Location']==args.location and book['SecurityID']==args.security_id
    levels=book.get('NoMDEntries') or []
    bids=[x for x in levels if x.get('MDEntryType')=='0']
    asks=[x for x in levels if x.get('MDEntryType')=='1']
    assert bids and asks,'missing bids or asks in MD, not a quoted book'
    assert all(Decimal(x['MDEntrySize'])>0 and Decimal(x['MDEntryPx'])>0 for x in levels)
    fingerprint=(book.get('LastUpdateId'),
       tuple(sorted((x['MDEntryType'],x['MDEntryPx'],x['MDEntrySize']) for x in levels)))
    seen.append(fingerprint)
    print('PUBLIC_MD_IMAGE_PASS sample='+str(i+1)+' update='+str(fingerprint[0])+
          ' bids='+str(len(bids))+' asks='+str(len(asks)))
    if i+1<args.samples:time.sleep(args.interval)
assert all(x==seen[0] for x in seen),'quote image changed during read-only probe'
print('PUBLIC_MD_STABLE_IMAGE_PASS samples='+str(len(seen)))
