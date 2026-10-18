#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${DEPLOY_DIR}/.env.prod}"
set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a
LOCATION="${CLEAN_LOCATION:-A02AA7}"
USER_NAME="${CLEAN_USER:-stressmaker_load064757}"
BASE_URL="http://127.0.0.1:${WEB_LISTEN_PORT}/httpapi/"
export LOCATION USER_NAME BASE_URL LOGIN_DEFAULT_PASSWORD
python3 - <<'PY'
import json,subprocess,os,sys
base=os.environ['BASE_URL']; loc=os.environ['LOCATION']; user=os.environ['USER_NAME']; pwd=os.environ.get('LOGIN_DEFAULT_PASSWORD','')
login={"serverName":"LoginSvr","method":"SYS.ATS.LOGIN","content":{"user_id":user,"user_name":user,"password":pwd,"method":"login","client_type":"WEB","cid":"CLEAN_STRESS_BASELINE","Location":loc}}
cp=subprocess.run(['curl','--noproxy','*','-fsS','--max-time','20','-H','Content-Type: application/json','--data',json.dumps(login),base],capture_output=True,text=True)
if cp.returncode: print(cp.stderr,file=sys.stderr); sys.exit(cp.returncode)
resp=json.loads(cp.stdout); data=resp.get('data') or {}
if int(resp.get('code',-1))!=0: print(json.dumps(resp),file=sys.stderr); sys.exit(2)
token=data.get('token') or data.get('sid') or data.get('sessionId') or data.get('session_id') or resp.get('sessionId')
if not token: print('login token missing',file=sys.stderr); sys.exit(3)
payload={"serverName":"OrderSvr","method":"cancelAllOrder","key":f"{loc}\u001f4\u001fBTCUSDT","content":{"UserID":user,"SecurityID":"BTCUSDT","MarketIndicator":"4","AlgoName":"cross","Location":loc}}
cp=subprocess.run(['curl','--noproxy','*','-fsS','--max-time','120','-H','Content-Type: application/json','-H',f'sessionId: {token}','--data',json.dumps(payload),base],capture_output=True,text=True)
if cp.returncode: print(cp.stderr,file=sys.stderr); sys.exit(cp.returncode)
resp=json.loads(cp.stdout)
print(json.dumps({"code":resp.get('code'),"msg":resp.get('msg')}))
if int(resp.get('code',-1))!=0: sys.exit(4)
PY
for i in $(seq 1 90); do
  c="$(docker exec -e MYSQL_PWD="${MYSQL_PASSWORD}" dc-saas-mysql mysql -u"${MYSQL_USERNAME}" -N -e "SELECT COUNT(*) FROM dc.dc_orders WHERE location='${LOCATION}' AND user_id='${USER_NAME}' AND ord_status IN ('New','Partially_Filled','Newing');" dc 2>/dev/null || echo x)"
  echo "active=${c}"
  [[ "${c}" == 0 ]] && break
  sleep 1
done
