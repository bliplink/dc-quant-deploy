#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Compatibility shim for older iproute2/ss versions that report process tuples
# as ("name",PID,FD) instead of ("name",pid=PID,fd=FD). The deployment core
# extracts listener PIDs using the newer pid= form, so normalize only this
# command's output without changing the host ss binary.
ss() {
  command ss "$@" |
    sed -E 's/\("([^"]+)",([0-9]+),([0-9]+)\)/("\1",pid=\2,fd=\3)/g'
}

# shellcheck source=deploy-core.sh
source "${ROOT_DIR}/deploy-core.sh" "$@"
