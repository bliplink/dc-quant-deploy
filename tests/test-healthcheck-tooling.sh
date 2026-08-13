#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

grep -q '^install_network_diagnostics()' "${ROOT_DIR}/prepare-host.sh"
grep -q 'install -y iproute' "${ROOT_DIR}/prepare-host.sh"
grep -q 'install -y iproute2' "${ROOT_DIR}/prepare-host.sh"
grep -q 'validating .* with container state and TCP connectivity' "${ROOT_DIR}/restart-service.sh"
grep -q 'validating .* with container state and TCP connectivity' "${ROOT_DIR}/deploy.sh"

echo 'health-check tooling test passed'
