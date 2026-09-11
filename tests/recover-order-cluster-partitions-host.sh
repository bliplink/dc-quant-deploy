#!/usr/bin/env bash
set -euo pipefail

ZK_CONTAINER="${ORDER_CLUSTER_ZK_CONTAINER:-dc-saas-zookeeper}"
ZK_SERVER="${ORDER_CLUSTER_ZK_SERVER:-127.0.0.1:32181}"
PARTITION_ROOT="${ORDER_CLUSTER_PARTITION_ROOT:-/dc/cluster/ordersvr/partitions}"
ORDER_A_CONTAINER="${ORDER_CLUSTER_A_CONTAINER:-dc-saas-ordersvr}"
ORDER_B_CONTAINER="${ORDER_CLUSTER_B_CONTAINER:-dc-saas-ordersvr-b}"
ORDER_C_CONTAINER="${ORDER_CLUSTER_C_CONTAINER:-dc-saas-ordersvr-c}"
ORDER_C_ENABLED="${ORDER_CLUSTER_C_ENABLED:-false}"
EXPECTED_PARTITIONS="${ORDER_CLUSTER_PARTITION_COUNT:-256}"
ASSIGNMENT_SETTLE_SECONDS="${ORDER_CLUSTER_ASSIGNMENT_SETTLE_SECONDS:-5}"
PARTITION_READY_TIMEOUT_SECONDS="${ORDER_CLUSTER_PARTITION_READY_TIMEOUT_SECONDS:-180}"
RESTART_AFTER_FENCE="${ORDER_CLUSTER_RESTART_AFTER_FENCE:-false}"
USE_CURRENT_FENCED="${ORDER_CLUSTER_RECOVERY_USE_CURRENT_FENCED:-false}"
TRADE_CONTAINER="${ORDER_CLUSTER_TRADE_CONTAINER:-dc-saas-tradesvr}"
ORDER_A_GW_PORT="${ORDER_CLUSTER_A_GW_PORT:-33036}"
ORDER_B_GW_PORT="${ORDER_CLUSTER_B_GW_PORT:-33041}"
ORDER_C_GW_PORT="${ORDER_CLUSTER_C_GW_PORT:-33044}"
ORDER_A_REPLICATION_PORT="${ORDER_CLUSTER_A_REPLICATION_PORT:-19121}"
ORDER_B_REPLICATION_PORT="${ORDER_CLUSTER_B_REPLICATION_PORT:-19122}"
ORDER_C_REPLICATION_PORT="${ORDER_CLUSTER_C_REPLICATION_PORT:-19123}"
TRADE_GW_PORT="${ORDER_CLUSTER_TRADE_GW_PORT:-33037}"

log() { printf '[order-cluster-recovery] %s\n' "$*"; }
die() { printf '[order-cluster-recovery] ERROR: %s\n' "$*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || die 'Run with sudo so Docker and protected runtime files are accessible'
command -v docker >/dev/null || die 'docker is required'
command -v python3 >/dev/null || die 'python3 is required'
[[ "${RESTART_AFTER_FENCE}" == true || "${RESTART_AFTER_FENCE}" == false ]] ||
  die 'ORDER_CLUSTER_RESTART_AFTER_FENCE must be true or false'
[[ "${USE_CURRENT_FENCED}" == true || "${USE_CURRENT_FENCED}" == false ]] ||
  die 'ORDER_CLUSTER_RECOVERY_USE_CURRENT_FENCED must be true or false'
containers=("${ZK_CONTAINER}" "${ORDER_A_CONTAINER}" "${ORDER_B_CONTAINER}")
[[ "${ORDER_C_ENABLED}" == true ]] && containers+=("${ORDER_C_CONTAINER}")
for container in "${containers[@]}"; do
  docker inspect "${container}" >/dev/null 2>&1 || die "Missing container ${container}"
done
if [[ "${RESTART_AFTER_FENCE}" == true ]]; then
  docker inspect "${TRADE_CONTAINER}" >/dev/null 2>&1 || die "Missing container ${TRADE_CONTAINER}"
fi

work_dir="$(mktemp -d)"
zk_input="${work_dir}/snapshot.commands"
zk_output="${work_dir}/snapshot.output"
assignments_json="${work_dir}/assignments.jsonl"
assignments_tsv="${work_dir}/assignments.tsv"
recovering_commands="${work_dir}/recovering.commands"
ready_tsv="${work_dir}/ready.tsv"
interactive_log="${work_dir}/interactive-zk.log"
zk_write_fd=''

cleanup() {
  if [[ -n "${zk_write_fd}" ]]; then
    printf 'quit\n' >&"${zk_write_fd}" 2>/dev/null || true
  fi
  rm -rf -- "${work_dir}"
}
trap cleanup EXIT

for ((index=0; index<EXPECTED_PARTITIONS; index++)); do
  printf 'get %s/P%03d\n' "${PARTITION_ROOT}" "${index}" >>"${zk_input}"
done
printf 'quit\n' >>"${zk_input}"
docker exec -i "${ZK_CONTAINER}" zkCli.sh -server "${ZK_SERVER}" \
  <"${zk_input}" >"${zk_output}" 2>&1 || true
grep -o '{"partitionId"[^}]*}' "${zk_output}" >"${assignments_json}" || true

python3 - "${assignments_json}" "${assignments_tsv}" "${EXPECTED_PARTITIONS}" "${ORDER_C_ENABLED}" <<'PY'
import json
import sys

source, target, expected, c_enabled = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4] == "true"
allowed = {"OrderSvrA", "OrderSvrB"}
if c_enabled:
    allowed.add("OrderSvrC")
rows = {}
with open(source, encoding="utf-8") as stream:
    for line in stream:
        value = json.loads(line)
        rows[value["partitionId"]] = value
if len(rows) != expected:
    raise SystemExit(f"expected {expected} assignments, found {len(rows)}")
with open(target, "w", encoding="utf-8", newline="\n") as stream:
    for partition_id in sorted(rows):
        value = rows[partition_id]
        primary = value.get("primary", "")
        replicas = value.get("replicas") or [value.get("replica", "")]
        learners = value.get("learners") or []
        if primary not in allowed or not replicas or any(node not in allowed for node in replicas + learners):
            raise SystemExit(f"unsupported topology for {partition_id}: {value}")
        if primary in replicas or len(set(replicas)) != len(replicas):
            raise SystemExit(f"invalid replica topology for {partition_id}: {value}")
        stream.write(f"{partition_id}\t{int(value['epoch'])}\n")
PY

max_epoch="$(awk -F '\t' 'BEGIN{max=0} $2>max{max=$2} END{print max}' "${assignments_tsv}")"
if [[ "${USE_CURRENT_FENCED}" == true ]]; then
  target_epoch="${ORDER_CLUSTER_RECOVERY_EPOCH:-${max_epoch}}"
else
  target_epoch="${ORDER_CLUSTER_RECOVERY_EPOCH:-$((max_epoch + 1))}"
fi
[[ "${target_epoch}" =~ ^[1-9][0-9]*$ ]] || die "Invalid recovery epoch ${target_epoch}"
if [[ "${USE_CURRENT_FENCED}" == true ]]; then
  (( target_epoch == max_epoch )) || die "Prepared recovery epoch ${target_epoch} must equal current max ${max_epoch}"
  python3 - "${assignments_json}" "${EXPECTED_PARTITIONS}" "${target_epoch}" <<'PY'
import json
import sys

path, expected_text, epoch_text = sys.argv[1:]
expected, epoch = int(expected_text), int(epoch_text)
rows = [json.loads(line) for line in open(path, encoding="utf-8")]
if len(rows) != expected or any(row.get("state") != "RECOVERING" or int(row.get("epoch", 0)) != epoch for row in rows):
    raise SystemExit("prepared recovery requires every assignment RECOVERING at one target epoch")
PY
else
  (( target_epoch > max_epoch )) || die "Recovery epoch ${target_epoch} must be greater than current max ${max_epoch}"
fi

python3 - "${assignments_json}" "${recovering_commands}" "${ready_tsv}" "${PARTITION_ROOT}" "${target_epoch}" "${USE_CURRENT_FENCED}" <<'PY'
import json
import sys

source, recovering_path, ready_path, root, epoch_text, use_current_text = sys.argv[1:]
epoch = int(epoch_text)
use_current = use_current_text == "true"
rows = sorted((json.loads(line) for line in open(source, encoding="utf-8")), key=lambda row: row["partitionId"])
with open(recovering_path, "w", encoding="utf-8", newline="\n") as recovering, \
        open(ready_path, "w", encoding="utf-8", newline="\n") as ready:
    for original in rows:
        partition_id = original["partitionId"]
        value = dict(original)
        value["epoch"] = epoch
        current_version = int(value.get("assignmentVersion") or 0)
        if "assignmentVersion" in value:
            value["assignmentVersion"] = current_version + 1
        value["state"] = "RECOVERING"
        recovering.write(f"set {root}/{partition_id} {json.dumps(value, separators=(',', ':'))}\n")
        if "assignmentVersion" in value:
            value["assignmentVersion"] = current_version + (1 if use_current else 2)
        value["state"] = "READY"
        ready.write(f"{partition_id}\t{value['primary']}\t{json.dumps(value, separators=(',', ':'))}\n")
PY

coproc ZK_CLIENT {
  docker exec -i "${ZK_CONTAINER}" zkCli.sh -server "${ZK_SERVER}" >"${interactive_log}" 2>&1
}
zk_write_fd="${ZK_CLIENT[1]}"

if [[ "${USE_CURRENT_FENCED}" == true ]]; then
  log "Using prepared RECOVERING topology at epoch ${target_epoch}."
else
  log "Fencing ${EXPECTED_PARTITIONS} partitions at epoch ${target_epoch} before recovery."
  cat "${recovering_commands}" >&"${zk_write_fd}"
  last_partition="$(tail -n 1 "${assignments_tsv}" | cut -f1)"
  printf 'get %s/%s\n' "${PARTITION_ROOT}" "${last_partition}" >&"${zk_write_fd}"

  fence_deadline=$((SECONDS + 60))
  until grep -Fq "\"partitionId\":\"${last_partition}\",\"epoch\":${target_epoch}" "${interactive_log}" \
      && grep -Fq '"state":"RECOVERING"' "${interactive_log}"; do
    (( SECONDS < fence_deadline )) || die 'ZooKeeper did not confirm the fenced assignment set'
    sleep 1
  done
fi

wait_for_tcp() {
  local port="$1" label="$2" deadline=$((SECONDS + 180))
  until python3 - "${port}" <<'PY'
import socket
import sys

sock = socket.socket()
sock.settimeout(1)
try:
    sock.connect(("127.0.0.1", int(sys.argv[1])))
except OSError:
    raise SystemExit(1)
finally:
    sock.close()
PY
  do
    (( SECONDS < deadline )) || die "${label} did not listen on port ${port} after the fenced restart"
    sleep 2
  done
}

if [[ "${RESTART_AFTER_FENCE}" == true ]]; then
  log "Fence confirmed; restarting OrderSvr cluster and TradeSvr inside epoch ${target_epoch}."
  restart_containers=("${ORDER_A_CONTAINER}" "${ORDER_B_CONTAINER}")
  [[ "${ORDER_C_ENABLED}" == true ]] && restart_containers+=("${ORDER_C_CONTAINER}")
  restart_containers+=("${TRADE_CONTAINER}")
  docker restart "${restart_containers[@]}" >/dev/null
  wait_for_tcp "${ORDER_A_GW_PORT}" "${ORDER_A_CONTAINER} gateway"
  wait_for_tcp "${ORDER_B_GW_PORT}" "${ORDER_B_CONTAINER} gateway"
  wait_for_tcp "${ORDER_A_REPLICATION_PORT}" "${ORDER_A_CONTAINER} replication"
  wait_for_tcp "${ORDER_B_REPLICATION_PORT}" "${ORDER_B_CONTAINER} replication"
  if [[ "${ORDER_C_ENABLED}" == true ]]; then
    wait_for_tcp "${ORDER_C_GW_PORT}" "${ORDER_C_CONTAINER} gateway"
    wait_for_tcp "${ORDER_C_REPLICATION_PORT}" "${ORDER_C_CONTAINER} replication"
  fi
  wait_for_tcp "${TRADE_GW_PORT}" "${TRADE_CONTAINER} gateway"
fi
sleep "${ASSIGNMENT_SETTLE_SECONDS}"

container_for_node() {
  case "$1" in
    OrderSvrA) printf '%s' "${ORDER_A_CONTAINER}" ;;
    OrderSvrB) printf '%s' "${ORDER_B_CONTAINER}" ;;
    OrderSvrC) printf '%s' "${ORDER_C_CONTAINER}" ;;
    *) return 1 ;;
  esac
}

partition_ready() {
  local container="$1" node="$2" partition_id="$3" since="$4"
  docker logs --since "${since}" "${container}" 2>&1 |
    grep -F "ORDER_PARTITION_PROMOTION_READY node:${node}, partition:${partition_id}, epoch:${target_epoch}" \
      >/dev/null
}

mapfile -t assignment_rows <"${ready_tsv}"
recovered=0
for ((offset=0; offset<${#assignment_rows[@]}; offset+=2)); do
  batch_started="$(date --iso-8601=seconds)"
  batch=()
  for ((item=offset; item<offset+2 && item<${#assignment_rows[@]}; item++)); do
    IFS=$'\t' read -r partition_id primary assignment_json <<<"${assignment_rows[item]}"
    batch+=("${partition_id}:${primary}")
    printf 'set %s/%s %s\n' "${PARTITION_ROOT}" "${partition_id}" "${assignment_json}" >&"${zk_write_fd}"
  done

  deadline=$((SECONDS + PARTITION_READY_TIMEOUT_SECONDS))
  while true; do
    pending=0
    for entry in "${batch[@]}"; do
      partition_id="${entry%%:*}"
      primary="${entry##*:}"
      container="$(container_for_node "${primary}")"
      partition_ready "${container}" "${primary}" "${partition_id}" "${batch_started}" || pending=$((pending + 1))
    done
    (( pending == 0 )) && break
    if (( SECONDS >= deadline )); then
      for entry in "${batch[@]}"; do
        partition_id="${entry%%:*}"
        primary="${entry##*:}"
        container="$(container_for_node "${primary}")"
        docker logs --since "${batch_started}" "${container}" 2>&1 | grep -F "partition:${partition_id}" | tail -n 20 >&2 || true
      done
      die "Timed out waiting for batch ${batch[*]} at epoch ${target_epoch}"
    fi
    sleep 2
  done

  recovered=$((recovered + ${#batch[@]}))
  if (( recovered % 16 == 0 || recovered == EXPECTED_PARTITIONS )); then
    log "Ready ${recovered}/${EXPECTED_PARTITIONS} partitions at epoch ${target_epoch}."
    stats_containers=("${ORDER_A_CONTAINER}" "${ORDER_B_CONTAINER}")
    [[ "${ORDER_C_ENABLED}" == true ]] && stats_containers+=("${ORDER_C_CONTAINER}")
    docker stats --no-stream --format '[order-cluster-recovery] RESOURCE {{.Name}} {{.CPUPerc}} {{.MemUsage}}' \
      "${stats_containers[@]}"
  fi
done

log "Recovery complete: ${recovered}/${EXPECTED_PARTITIONS} partitions READY at epoch ${target_epoch}."
