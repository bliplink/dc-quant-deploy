#!/usr/bin/env bash
# T465 — Fresh Demo only. Create *different* 256-bit secrets for every
# physical node and separate SOURCE / authorized-reader roles.
# Never change existing credentials or print their contents.
set -euo pipefail
umask 077
if [[ "$#" -ne 4 ]]; then
  echo "usage: $0 ABSOLUTE_EMPTY_ROOT OrderSvr|TradeSvr NODE_A NODE_B" >&2
  exit 64
fi
root="$1"
service="$2"
a="$3"
b="$4"
[[ "$root" = /* && "$root" != "/" ]] || { echo "absolute, non-root storage required" >&2; exit 64; }
[[ "$service" == OrderSvr || "$service" == TradeSvr ]] || { echo "unsupported service" >&2; exit 64; }
[[ "$a" =~ ^[A-Za-z0-9_.-]{1,64}$ && "$b" =~ ^[A-Za-z0-9_.-]{1,64}$ && "$a" != "$b" ]] || { echo "two distinct physical node ids required" >&2; exit 64; }
command -v openssl >/dev/null || { echo "openssl required" >&2; exit 69; }

# Never follow a preexisting service directory/symlink and NEVER overwrite an
# existing physical key. On a failed partial run abandon this namespace and
# create another fresh Demo namespace; no rotation without an explicit plan.
mkdir -p -- "$root"
[[ ! -L "$root" ]] || { echo "root symlink refused" >&2; exit 73; }
serviceRoot="$root/$service"
if [[ -e "$serviceRoot" || -L "$serviceRoot" ]]; then
  echo "physical credentials already exist; refusing overwrite" >&2
  exit 73
fi
mkdir -m 700 -- "$serviceRoot"
mkdir -m 700 -- "$serviceRoot/source" "$serviceRoot/reader"
for role in source reader; do
  for node in "$a" "$b"; do
    file="$serviceRoot/$role/$node.hmac"
    [[ ! -e "$file" && ! -L "$file" ]] || { echo "existing physical secret refused" >&2; exit 73; }
    # The 64 lowercase hex characters are generated from 32 kernel-random
    # bytes; openssl adds one newline, which CommonPinnedRecoveryHmacKeyRing
    # explicitly accepts. No secrets in stdout, process args, or Git.
    openssl rand -hex 32 > "$file"
    chmod 600 "$file"
  done
done
# Check that signer and reader keys differ, and the two physical signer keys
# differ. compare without printing or reading key contents into shell vars.
cmp -s "$serviceRoot/source/$a.hmac" "$serviceRoot/source/$b.hmac" && { echo "duplicate source keys refused" >&2; exit 74; }
for node in "$a" "$b"; do
  cmp -s "$serviceRoot/source/$node.hmac" "$serviceRoot/reader/$node.hmac" && { echo "reader/source key not separated" >&2; exit 74; }
done
echo "T465_PHYSICAL_RECOVERY_HMAC_PROVISIONED_UNDER_NEW_DEMO_NAMESPACE"
echo "source directory: $serviceRoot/source"
echo "reader directory: $serviceRoot/reader"