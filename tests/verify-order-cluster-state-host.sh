#!/usr/bin/env bash
set -euo pipefail

ZK_CONTAINER="${ORDER_CLUSTER_ZK_CONTAINER:-dc-saas-zookeeper}"
ZK_ENDPOINT="${ORDER_CLUSTER_ZK_ENDPOINT:-127.0.0.1:32181}"
PARTITION_ROOT="${ORDER_CLUSTER_PARTITION_ROOT:-/dc/cluster/ordersvr/partitions}"
PARTITION_COUNT="${ORDER_CLUSTER_PARTITION_COUNT:-256}"
DATA_ROOT="${ORDER_CLUSTER_DATA_ROOT:-/data/dc-saas-runtime/data}"
WEB_PORT="${WEB_LISTEN_PORT:-18088}"
VERIFY_LEARNERS="${ORDER_CLUSTER_VERIFY_LEARNERS:-false}"

log() { printf '[order-cluster-verify] %s\n' "$*"; }
die() { printf '[order-cluster-verify] ERROR: %s\n' "$*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || die 'Run with sudo so Docker and runtime state are readable'
command -v docker >/dev/null || die 'docker is required'
command -v python3 >/dev/null || die 'python3 is required'
command -v curl >/dev/null || die 'curl is required'

work_dir="$(mktemp -d)"
trap 'rm -rf -- "${work_dir}"' EXIT
zk_commands="${work_dir}/zk.commands"
zk_output="${work_dir}/zk.output"
assignments="${work_dir}/assignments.jsonl"

for ((index=0; index<PARTITION_COUNT; index++)); do
  printf 'get %s/P%03d\n' "${PARTITION_ROOT}" "${index}" >>"${zk_commands}"
done
printf 'quit\n' >>"${zk_commands}"
docker exec -i "${ZK_CONTAINER}" zkCli.sh -server "${ZK_ENDPOINT}" \
  <"${zk_commands}" >"${zk_output}" 2>&1 || true
grep -o '{"partitionId"[^}]*}' "${zk_output}" >"${assignments}" || true

python3 - "${assignments}" "${PARTITION_COUNT}" "${DATA_ROOT}" "${VERIFY_LEARNERS}" <<'PY'
import collections
import json
import os
import sys

assignment_path, expected_text, data_root, verify_learners_text = sys.argv[1:]
expected = int(expected_text)
verify_learners = verify_learners_text == "true"
allowed_nodes = {"OrderSvrA", "OrderSvrB", "OrderSvrC"}
rows = [json.loads(line) for line in open(assignment_path, encoding="utf-8")]
by_id = {row.get("partitionId"): row for row in rows}
expected_ids = {f"P{index:03d}" for index in range(expected)}
if set(by_id) != expected_ids:
    missing = sorted(expected_ids - set(by_id))
    extra = sorted(set(by_id) - expected_ids)
    raise SystemExit(f"assignment set mismatch missing={missing[:8]} extra={extra[:8]}")
states = collections.Counter(row.get("state") for row in rows)
epochs = collections.Counter(row.get("epoch") for row in rows)
primaries = collections.Counter(row.get("primary") for row in rows)
replicas = collections.Counter(
    node for row in rows for node in (row.get("replicas") or [row.get("replica")])
)
learners = collections.Counter(node for row in rows for node in (row.get("learners") or []))
if states != {"READY": expected}:
    raise SystemExit(f"not all assignments are READY: {dict(states)}")
if len(epochs) != 1:
    raise SystemExit(f"assignments span multiple epochs: {dict(epochs)}")
for partition_id, row in by_id.items():
    primary = row.get("primary")
    replica_nodes = row.get("replicas") or [row.get("replica")]
    learner_nodes = row.get("learners") or []
    nodes = [primary] + replica_nodes + learner_nodes
    if primary not in allowed_nodes or not replica_nodes or any(node not in allowed_nodes for node in nodes):
        raise SystemExit(f"invalid topology {partition_id}: {row}")
    if primary in replica_nodes or len(set(replica_nodes)) != len(replica_nodes):
        raise SystemExit(f"invalid replicas {partition_id}: {row}")

uppercase_sn = 0
for partition_id, assignment in sorted(by_id.items()):
    values = []
    replica_nodes = assignment.get("replicas") or [assignment.get("replica")]
    nodes = [assignment.get("primary")] + replica_nodes
    if verify_learners:
        nodes += assignment.get("learners") or []
    for node in dict.fromkeys(nodes):
        path = os.path.join(data_root, node, "snapshot", partition_id, "snapshot.json")
        if not os.path.isfile(path):
            raise SystemExit(f"missing snapshot: {path}")
        with open(path, encoding="utf-8") as stream:
            value = json.load(stream)
        if value.get("partitionId") != partition_id:
            raise SystemExit(f"snapshot partition mismatch: {path}")
        if value.get("epoch") != assignment.get("epoch"):
            raise SystemExit(
                f"snapshot epoch mismatch {partition_id} node={node} "
                f"snapshot={value.get('epoch')} assignment={assignment.get('epoch')}"
            )
        uppercase_sn += sum(
            1
            for book in value.get("books", [])
            for order in book.get("orders", [])
            if "SN" in order
        )
        values.append(value)
    if any(value != values[0] for value in values[1:]):
        raise SystemExit(f"assigned snapshot mismatch: {partition_id} nodes={nodes}")
if uppercase_sn:
    raise SystemExit(f"snapshots contain {uppercase_sn} side-effectful uppercase SN fields")

epoch = next(iter(epochs))
print(f"partitions={expected} ready={states['READY']} epoch={epoch}")
print(f"primaries={dict(sorted(primaries.items()))}")
print(f"replicas={dict(sorted(replicas.items()))}")
print(f"learners={dict(sorted(learners.items()))}")
print(f"snapshot_sets_equal={expected} verify_learners={verify_learners} uppercase_SN=0")
PY

route_response="$(curl -fsS --max-time 10 -H 'Content-Type: application/json' \
  --data '{"serverName":"OrderSvr","method":"__cluster_state_verify__","key":"CLUSTER_VERIFY\u001f4\u001fBTCUSDT","content":{"Location":"CLUSTER_VERIFY","MarketIndicator":"4","SecurityID":"BTCUSDT"}}' \
  "http://127.0.0.1:${WEB_PORT}/httpapi/")"
grep -Fq 'is not Online' <<<"${route_response}" && die 'logical OrderSvr route is offline'
grep -Fq 'handler:__cluster_state_verify__ does not exist.' <<<"${route_response}" \
  || die "unexpected logical OrderSvr route response: ${route_response}"

containers=(dc-saas-ordersvr dc-saas-ordersvr-b dc-saas-gateway)
if grep -qE '"(primary|replica)":"OrderSvrC"|"replicas":\[[^]]*"OrderSvrC"|"learners":\[[^]]*"OrderSvrC"' "${assignments}"; then
  containers+=(dc-saas-ordersvr-c)
fi
for container in "${containers[@]}"; do
  status="$(docker inspect -f '{{.State.Status}}' "${container}")"
  restarts="$(docker inspect -f '{{.RestartCount}}' "${container}")"
  oom="$(docker inspect -f '{{.State.OOMKilled}}' "${container}")"
  image="$(docker inspect -f '{{.Config.Image}}' "${container}")"
  [[ "${status}" == 'running' ]] || die "${container} is ${status}"
  [[ "${oom}" == 'false' ]] || die "${container} was OOM-killed"
  log "${container} image=${image} status=${status} restarts=${restarts} oom=${oom}"
done

log 'PASS: assignments, snapshots, route and container state are consistent.'
