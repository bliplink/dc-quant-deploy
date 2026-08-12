#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-}"

if [[ -z "${ENV_FILE}" || ! -f "${ENV_FILE}" ]]; then
  echo "Usage: $0 ENV_FILE" >&2
  exit 1
fi

awk '
  { sub(/\r$/, "", $0) }
  /^[[:space:]]*($|#)/ { next }
  !/^[A-Za-z_][A-Za-z0-9_]*=/ {
    printf "Invalid environment assignment at %s:%d. Expected KEY=VALUE.\n", FILENAME, NR > "/dev/stderr"
    failed = 1
    next
  }
  {
    value = substr($0, index($0, "=") + 1)
    first = substr(value, 1, 1)
    last = substr(value, length(value), 1)
    quoted = (first == "\047" && last == "\047") || (first == "\"" && last == "\"")
    if (!quoted && value ~ /[|;&<>[:space:]]/) {
      printf "Unsafe unquoted value at %s:%d. Enclose values containing spaces or shell operators in quotes.\n", FILENAME, NR > "/dev/stderr"
      failed = 1
    }
  }
  END {
    if (failed) {
      print "Example: QUANTSVR_BOT_ADMIN_LIST=\047id1|id2\047" > "/dev/stderr"
      exit 1
    }
  }
' "${ENV_FILE}"

# The file is sourced by deployment scripts, so reject malformed shell syntax too.
bash -n "${ENV_FILE}"
