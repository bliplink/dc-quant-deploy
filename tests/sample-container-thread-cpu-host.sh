#!/usr/bin/env bash
set -euo pipefail
CONTAINERS="${THREAD_SAMPLE_CONTAINERS:-dc-saas-ordersvr dc-saas-ordersvr-b}"
SECONDS_TO_SAMPLE="${THREAD_SAMPLE_SECONDS:-5}"
TOP_N="${THREAD_SAMPLE_TOP_N:-20}"
[[ "${SECONDS_TO_SAMPLE}" =~ ^[1-9][0-9]*$ ]] || { echo 'THREAD_SAMPLE_SECONDS must be a positive integer' >&2; exit 2; }
[[ "${TOP_N}" =~ ^[1-9][0-9]*$ ]] || { echo 'THREAD_SAMPLE_TOP_N must be a positive integer' >&2; exit 2; }
command -v docker >/dev/null 2>&1 || { echo 'docker is required' >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo 'python3 is required on the Docker host' >&2; exit 2; }
for container in ${CONTAINERS}; do
  pid="$(docker inspect "${container}" --format '{{.State.Pid}}' 2>/dev/null || true)"
  [[ "${pid}" =~ ^[1-9][0-9]*$ ]] || { echo "${container}: not running"; continue; }
  echo "=== ${container} hostPid=${pid} sample=${SECONDS_TO_SAMPLE}s ==="
  python3 - "${pid}" "${SECONDS_TO_SAMPLE}" "${TOP_N}" <<'PY'
import os,sys,time
pid=int(sys.argv[1]); duration=int(sys.argv[2]); topn=int(sys.argv[3]); base=f'/proc/{pid}/task'
def snap():
    out={}
    try: tids=os.listdir(base)
    except OSError: return out
    for tid in tids:
        try:
            stat=open(f'{base}/{tid}/stat').read().split()
            ticks=int(stat[13])+int(stat[14])
            name=open(f'{base}/{tid}/comm').read().strip()
            out[int(tid)]=(ticks,name)
        except (OSError,ValueError,IndexError): pass
    return out
a=snap(); time.sleep(duration); b=snap(); hz=os.sysconf(os.sysconf_names['SC_CLK_TCK']); rows=[]
for tid,(ticks2,name) in b.items():
    old=a.get(tid)
    if not old: continue
    delta=ticks2-old[0]
    if delta>0: rows.append((delta/hz/duration*100.0,tid,name))
if not rows:
    print('no measurable CPU ticks')
else:
    for cpu,tid,name in sorted(rows,reverse=True)[:topn]:
        print(f'{cpu:7.2f}% tid={tid:<7} {name}')
PY
done
