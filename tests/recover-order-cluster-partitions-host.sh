#!/usr/bin/env bash
set -euo pipefail

ZK_CONTAINER="${ORDER_CLUSTER_ZK_CONTAINER:-dc-saas-zookeeper}"
ZK_SERVER="${ORDER_CLUSTER_ZK_SERVER:-127.0.0.1:32181}"
PARTITION_ROOT="${ORDER_CLUSTER_PARTITION_ROOT:-/dc/cluster/ordersvr/partitions}"
ORDER_A_CONTAINER="${ORDER_CLUSTER_A_CONTAINER:-dc-saas-ordersvr}"
ORDER_B_CONTAINER="${ORDER_CLUSTER_B_CONTAINER:-dc-saas-ordersvr-b}"
EXPECTED_PARTITIONS="${ORDER_CLUSTER_PARTITION_COUNT:-256}"
ASSIGNMENT_SETTLE_SECONDS="${ORDER_CLUSTER_ASSIGNMENT_SETTLE_SECONDS:-5}"
PARTITION_READY_TIMEOUT_SECONDS="${ORDER_CLUSTER_PARTITION_READY_TIMEOUT_SECONDS:-180}"

log() { printf '[order-cluster-recovery] %s\n' "$*"; }
die() { printf '[order-cluster-recovery] ERROR: %s\n' "$*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || die 'Run with sudo so Docker and protected runtime files are accessible'
command -v docker >/dev/null || die 'docker is required'
command -v python3 >/dev/null || die 'python3 is required'
for container in "${ZK_CONTAINER}" "${ORDER_A_CONTAINER}" "${ORDER_B_CONTAINER}"; do
  docker inspect "${container}" >/dev/null 2>&1 || die "Missing container ${container}"
done

work_dir="$(mktemp -d)"
zk_input="${work_dir}/snapshot.commands"
zk_output="${work_dir}/snapshot.output"
assignments_json="${work_dir}/assignments.jsonl"
assignments_tsv="${work_dir}/assignments.tsv"
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

python3 - "${assignments_json}" "${assignments_tsv}" "${EXPECTED_PARTITIONS}" <<'PY'
import json
import sys

source, target, expected = sys.argv[1], sys.argv[2], int(sys.argv[3])
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
        replica = value.get("replica", "")
        if primary not in ("OrderSvrA", "OrderSvrB") or replica not in ("OrderSvrA", "OrderSvrB"):
            raise SystemExit(f"unsupported topology for {partition_id}: {value}")
        stream.write(f"{partition_id}\t{int(value['epoch'])}\t{primary}\t{replica}\n")
PY

max_epoch="$(awk -F '\t' 'BEGIN{max=0} $2>max{max=$2} END{print max}' "${assignments_tsv}")"
target_epoch="${ORDER_CLUSTER_RECOVERY_EPOCH:-$((max_epoch + 1))}"
[[ "${target_epoch}" =~ ^[1-9][0-9]*$ ]] || die "Invalid recovery epoch ${target_epoch}"
(( target_epoch > max_epoch )) || die "Recovery epoch ${target_epoch} must be greater than current max ${max_epoch}"

log "Fencing ${EXPECTED_PARTITIONS} partitions at epoch ${target_epoch} before recovery."
coproc ZK_CLIENT {
  docker exec -i "${ZK_CONTAINER}" zkCli.sh -server "${ZK_SERVER}" >"${interactive_log}" 2>&1
}
zk_write_fd="${ZK_CLIENT[1]}"

while IFS=$'\t' read -r partition_id _ primary replica; do
  printf 'set %s/%s {"partitionId":"%s","epoch":%s,"primary":"%s","replica":"%s","state":"RECOVERING"}\n' \
    "${PARTITION_ROOT}" "${partition_id}" "${partition_id}" "${target_epoch}" "${primary}" "${replica}" \
    >&"${zk_write_fd}"
done <"${assignments_tsv}"
last_partition="$(tail -n 1 "${assignments_tsv}" | cut -f1)"
printf 'get %s/%s\n' "${PARTITION_ROOT}" "${last_partition}" >&"${zk_write_fd}"

fence_deadline=$((SECONDS + 60))
until grep -Fq "\"partitionId\":\"${last_partition}\",\"epoch\":${target_epoch}" "${interactive_log}" \
    && grep -Fq '"state":"RECOVERING"' "${interactive_log}"; do
  (( SECONDS < fence_deadline )) || die 'ZooKeeper did not confirm the fenced assignment set'
  sleep 1
done
sleep "${ASSIGNMENT_SETTLE_SECONDS}"

container_for_node() {
  case "$1" in
    OrderSvrA) printf '%s' "${ORDER_A_CONTAINER}" ;;
    OrderSvrB) printf '%s' "${ORDER_B_CONTAINER}" ;;
    *) return 1 ;;
  esac
}

partition_ready() {
  local container="$1" node="$2" partition_id="$3" since="$4"
  docker logs --since "${since}" "${container}" 2>&1 |
    grep -Fq "ORDER_PARTITION_PROMOTION_READY node:${node}, partition:${partition_id}, epoch:${target_epoch}"
}

mapfile -t assignment_rows <"${assignments_tsv}"
recovered=0
for ((offset=0; offset<${#assignment_rows[@]}; offset+=2)); do
  batch_started="$(date --iso-8601=seconds)"
  batch=()
  for ((item=offset; item<offset+2 && item<${#assignment_rows[@]}; item++)); do
    IFS=$'\t' read -r partition_id _ primary replica <<<"${assignment_rows[item]}"
    batch+=("${partition_id}:${primary}")
    printf 'set %s/%s {"partitionId":"%s","epoch":%s,"primary":"%s","replica":"%s","state":"READY"}\n' \
      "${PARTITION_ROOT}" "${partition_id}" "${partition_id}" "${target_epoch}" "${primary}" "${replica}" \
      >&"${zk_write_fd}"
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
    docker stats --no-stream --format '[order-cluster-recovery] RESOURCE {{.Name}} {{.CPUPerc}} {{.MemUsage}}' \
      "${ORDER_A_CONTAINER}" "${ORDER_B_CONTAINER}"
  fi
done

log "Recovery complete: ${recovered}/${EXPECTED_PARTITIONS} partitions READY at epoch ${target_epoch}."
