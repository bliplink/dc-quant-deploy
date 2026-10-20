#!/usr/bin/env python3
"""Read-only Demo audit for crossed New orders on a tenant-created market.

Checks MySQL projection only. It is NOT a substitute for an actual matcher
fault injection, matching-engine in-memory order book, or Trade reconciliation.
"""
import argparse
import json
import re
import subprocess
import time
from decimal import Decimal


def read_select(sql):
    if not sql.startswith('SELECT ') or ';' in sql:
        raise ValueError('only a single SELECT query is allowed')
    p = subprocess.run(
        ['docker', 'exec', 'dc-saas-mysql', 'sh', '-c',
         'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N dc -e "$1"', '--', sql],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=20)
    if p.returncode:
        raise RuntimeError('read-only projected order check unavailable')
    return [line.split('\t') for line in p.stdout.splitlines()]


def audit(location, security_id):
    results=read_select(
        'SELECT side,ord_status,price,leaves_qty,market_indicator,algo_name,'
        'user_id,order_id FROM dc_orders WHERE location="'+location+'" '
        'AND security_id="'+security_id+'"')
    rows=[dict(side=r[0],status=r[1],price=Decimal(r[2]),
               remaining=Decimal(r[3]),indicator=r[4],algo=r[5],
               user=r[6],order=r[7]) for r in results]
    bids=[r for r in rows if r['side']=='Buy' and r['status']=='New'
          and r['remaining']>0]
    asks=[r for r in rows if r['side']=='Sell' and r['status']=='New'
          and r['remaining']>0]
    crossings=[(bid,ask) for bid in bids for ask in asks
               if bid['indicator']==ask['indicator'] and bid['algo']==ask['algo']
               and bid['user']!=ask['user'] and bid['price']>=ask['price']]
    counts={status:sum(1 for r in rows if r['status']==status)
            for status in sorted(set(r['status'] for r in rows))}
    duplicates=read_select(
        'SELECT exec_id,COUNT(*) FROM dc_orders_execorders WHERE '
        'location="'+location+'" AND security_id="'+security_id+'" '
        'AND exec_id IS NOT NULL GROUP BY exec_id HAVING COUNT(*)>1')
    return {'tenant':location,'security_id':security_id,'orders':len(rows),
            'statuses':counts,'crossed_new_pairs':len(crossings),
            'duplicated_execution_ids':len(duplicates)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tenant',required=True)
    parser.add_argument('--symbol',default='BTC003USDT')
    parser.add_argument('--watch-seconds',type=int,default=0,
                        help='Optional recheck delay to detect persistent crossed orders')
    args=parser.parse_args()
    if not re.fullmatch(r'[A-Z0-9]{6}',args.tenant):
        parser.error('tenant must be six uppercase letters/digits')
    if not re.fullmatch(r'[A-Z0-9_]{2,32}',args.symbol):
        parser.error('invalid product security_id')
    if not 0 <= args.watch_seconds <= 60:
        parser.error('watch-seconds must be 0..60')
    first=audit(args.tenant,args.symbol)
    print(json.dumps(first,sort_keys=True))
    if args.watch_seconds:
        time.sleep(args.watch_seconds)
        followup=audit(args.tenant,args.symbol)
        print(json.dumps(followup,sort_keys=True))
        return 2 if followup['crossed_new_pairs'] or followup['duplicated_execution_ids'] else 0
    return 2 if first['crossed_new_pairs'] or first['duplicated_execution_ids'] else 0


if __name__=='__main__':
    raise SystemExit(main())
