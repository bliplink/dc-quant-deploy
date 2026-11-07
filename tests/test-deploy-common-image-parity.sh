#!/usr/bin/env bash
set -euo pipefail

# No Docker daemon or running service is touched. Exercise the exact
# pre-start image gates from deploy-saas.sh with controlled Docker labels.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
eval "$(sed -n '/^require_immutable_cluster_image() {/,/^wait_for_health() {/p' "${ROOT}/deploy-saas.sh" | sed '$d')"

fail() { printf '[test-common-image-parity] FAIL: %s\n' "$*" >&2; exit 1; }
die() { printf '[test-common-image-parity] REJECT: %s\n' "$*" >&2; exit 91; }
log() { :; }

GW_IMAGE_REPOSITORY=test/gateway
ORDERSVR_IMAGE_REPOSITORY=test/ordersvr
MDSVR_IMAGE_REPOSITORY=test/mdsvr
TRADESVR_IMAGE_REPOSITORY=test/tradesvr
GW_TAG=sha-test
ORDERSVR_TAG=sha-test
MDSVR_TAG=sha-test
TRADESVR_TAG=sha-test
ORDER_CLUSTER_ENABLED=true
MD_CLUSTER_ENABLED=true
TRADE_CLUSTER_ENABLED=true

SHA_A="$(printf '%064d' 0 | tr 0 a)"
SHA_B="$(printf '%064d' 0 | tr 0 b)"
GW_SHA="$SHA_A"
ORDER_SHA="$SHA_A"
MD_SHA="$SHA_A"
TRADE_SHA="$SHA_A"
GW_REV=common-release-1
ORDER_REV=common-release-1
MD_REV=common-release-1
TRADE_REV=common-release-1

docker() {
  [[ "${1:-}" == image && "${2:-}" == inspect && "${4:-}" == --format ]] ||
    return 88
  local service label
  case "${3:-}" in
    test/gateway:sha-test) service=GW ;;
    test/ordersvr:sha-test) service=ORDER ;;
    test/mdsvr:sha-test) service=MD ;;
    test/tradesvr:sha-test) service=TRADE ;;
    *) return 89 ;;
  esac
  case "${5:-}" in
    *dc.common.jar.sha256*) label=SHA ;;
    *dc.common.revision*) label=REV ;;
    *) return 90 ;;
  esac
  local key="${service}_${label}"
  printf '%s\n' "${!key}"
}

expect_pass() {
  local name="$1"; shift
  if ! ( "$@" >/dev/null ); then fail "${name} unexpectedly rejected"; fi
}
expect_reject() {
  local name="$1"; shift
  if ( "$@" >/dev/null 2>&1 ); then fail "${name} unexpectedly passed"; fi
}

expect_pass equal_order verify_order_cluster_images
expect_pass equal_md verify_md_cluster_images
expect_pass equal_trade verify_trade_cluster_images

ORDER_SHA="$SHA_B"
expect_reject mismatched_order_sha verify_order_cluster_images
ORDER_SHA="$SHA_A"

MD_SHA="$SHA_B"
expect_reject mismatched_md_sha verify_md_cluster_images
MD_SHA="$SHA_A"

TRADE_SHA="$SHA_B"
expect_reject mismatched_trade_sha verify_trade_cluster_images
TRADE_SHA="$SHA_A"

TRADE_REV=common-release-2
expect_reject mismatched_trade_revision verify_trade_cluster_images
TRADE_REV=common-release-1

TRADE_SHA=""
expect_reject missing_trade_sha verify_trade_cluster_images
TRADE_SHA="$SHA_A"

GW_SHA=""
expect_reject missing_gateway_sha verify_trade_cluster_images
GW_SHA="$SHA_A"

TRADE_CLUSTER_ENABLED=false
TRADE_SHA="$SHA_B"
expect_pass disabled_trade_cluster verify_trade_cluster_images

printf '[test-common-image-parity] PASS: equal accepted; divergent SHA/revision and absent SHA rejected for Order/MD/Trade\n'