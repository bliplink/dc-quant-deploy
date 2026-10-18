#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/.env.prod}"
LOCATION="${CLOSE_LOCATION:-A02AA7}"
MAKER="${CLOSE_MAKER:?CLOSE_MAKER is required}"
TAKER="${CLOSE_TAKER:?CLOSE_TAKER is required}"
QTY="${CLOSE_QTY:?CLOSE_QTY is required}"
PRICE="${CLOSE_PRICE:-60000}"
set -a
. "${ENV_FILE}"
set +a
export LOCATION MAKER TAKER QTY PRICE LOGIN_DEFAULT_PASSWORD WEB_LISTEN_PORT
python3 - <<'PY'
import json, os, subprocess, sys, time
base=f"http://127.0.0.1:{os.environ['WEB_LISTEN_PORT']}/httpapi/"
loc=os.environ['LOCATION']; maker=os.environ['MAKER']; taker=os.environ['TAKER']; qty=os.environ['QTY']; price=os.environ['PRICE']; pwd=os.environ.get('LOGIN_DEFAULT_PASSWORD','')

def invoke(payload, token=None, timeout=30):
    cmd=['curl','--noproxy','*','-fsS','--max-time',str(timeout),'-H','Content-Type: application/json']
    if token: cmd += ['-H',f'sessionId: {token}']
    cmd += ['--data',json.dumps(payload,separators=(',',':')),base]
    cp=subprocess.run(cmd,capture_output=True,text=True)
    if cp.returncode:
        print(cp.stderr,file=sys.stderr); raise SystemExit(cp.returncode)
    data=json.loads(cp.stdout)
    if int(data.get('code',-1)) != 0:
        print(cp.stdout,file=sys.stderr); raise SystemExit(2)
    return data

def login(user):
    r=invoke({'serverName':'LoginSvr','method':'SYS.ATS.LOGIN','content':{'user_id':user,'user_name':user,'password':pwd,'method':'login','client_type':'WEB','cid':'STRESS_CLOSE','Location':loc}})
    d=r.get('data') or {}
    token=d.get('token') or d.get('sid') or d.get('sessionId') or d.get('session_id')
    if not token: raise SystemExit('missing login token')
    return token

def place(user,token,side,posside,clord):
    content={'OCType':'CLOSE','OrderQty':qty,'OrdType':'Limit','ClOrdID':clord,'Terminal':'API','AlgoName':'cross','Side':side,'PositionSide':posside,'Price':price,'UserID':user,'MarketIndicator':'4','TimeInForce':'GTC','SecurityID':'BTCUSDT','ReduceOnly':'true','Location':loc}
    return invoke({'serverName':'OrderSvr','method':'placeOrder','key':f'{loc}\x1f4\x1fBTCUSDT','content':content},token,30)
mt=login(maker); tt=login(taker)
stamp=str(int(time.time()*1000))
a=place(maker,mt,'Buy','Short',f'CLOSE-{stamp}-SHORT')
b=place(taker,tt,'Sell','Long',f'CLOSE-{stamp}-LONG')
print(json.dumps({'shortCloseOrderId':a.get('info1'),'longCloseOrderId':b.get('info1')}))
PY
for _ in $(seq 1 90); do
  row="$(docker exec -e MYSQL_PWD="${MYSQL_PASSWORD}" dc-saas-mysql mysql -u"${MYSQL_USERNAME}" -N -e "SELECT CONCAT(COALESCE(SUM(ABS(long_position)+ABS(short_position)),0),'|',COALESCE(SUM(ABS(long_used_margin)+ABS(short_used_margin)),0)) FROM dc.dc_orders_position WHERE location='${LOCATION}' AND user_id IN ('${MAKER}','${TAKER}') AND security_id='BTCUSDT';" dc)"
  echo "position_state=${row}"
  [[ "${row}" == "0.000000000|0.000000000" || "${row}" == "0.000000000000000000|0.000000000000000000" ]] && exit 0
  sleep 1
done
exit 1
