#!/usr/bin/env bash
# T154 actual Order/Trade business-domain functional smoke.
# Executes real original Order/Trade business classes, Common RSA Netty
# physically signed WAL/Custody and matcher/risk/financial tests on THIS Mac.
# Does not grant READY, start a Spring service, touch Demo, ZK, or user funds.
set -euo pipefail
if [ "$#" -ne 3 ]; then
  echo "Usage: bash run-t154-order-trade-business-smoke.sh <Order-source> <Trade-source> <existing-Demo-RSA-root>" >&2
  exit 2
fi
order="$1"
trade="$2"
keys="$3"
for path in "$order" "$trade" "$keys"; do
  if [[ "$path" != /* ]] || [ ! -d "$path" ]; then
    echo "T154_DENIED: all three arguments must be existing absolute directories" >&2
    exit 1
  fi
done
if [ ! -f "$keys/a/node.pk8" ] || [ ! -f "$keys/b/node.pk8" ] ||
   [ ! -f "$keys/public/CommonHaDemoA.pub.der" ] ||
   [ ! -f "$keys/public/CommonHaDemoB.pub.der" ]; then
  echo "T154_DENIED: original, existing Demo A/B RSA required" >&2
  exit 1
fi
if [ "$(git -C "$order" rev-parse HEAD)" != "4b1c7d8fce274208f4d6f74d7b70998775ad0a35" ] ||
   [ "$(git -C "$trade" rev-parse HEAD)" != "2811eb262317206ef840eec9312a597ce9916bc8" ]; then
  echo "T154_DENIED: expected T152 Order/Trade production source commits missing" >&2
  exit 1
fi
mvn="/Users/kong/.opentradingcore/local-ha-build-20261015/tools/apache-maven-3.9.11/bin/mvn"
test -x "$mvn"
orderTests=(
  OrderCommonSinglePartitionRealStateTest
  OrderCommandDrainFacadeIntegrationTest
  OrderFacadePendingCancelTest
  OrderFacadeMassCancelTest
  OrderBookTest
  PendingNewOrderReconcilerTest
  TradeExecOrderLifecycleSyncTest
  CrossStrategyTimeInForceTest
  SelfTradePreventionModeTest
  MarketOrderSafetyTest
  TradeExecOrderCallbackBatchTest
  TradeExecOrderBusinessPersistenceTest
  TradeExecOrderTimeoutRetryTest
  CrossStrategyWalFirstBatchTest
  ProtectiveOrderSemanticsTest
)
tradeTests=(
  TradeCertifiedNewingLiveNettyTest
  TradeCertifiedNewingLiveFacadeTest
  TradeProcessOrderRealRiskPlanTest
  TradeCommonPhysicalFinancialStateTest
  PositionFacadeTest
  AccountBalanceFacadeTest
  TradeExecutionAffectedStateRecorderTest
  ExecutionDeduplicatorTest
  MySqlDBTradeDaoPostingTest
  TradeCashStateRecorderTest
  TradeFundingStateRecorderTest
  TradePositionAdlStateRecorderTest
  TradeBankruptcyStateRecorderTest
  TradeRecoveryApplierTest
)
run_group(){
  local source="$1" group="$2" expected="$3"
  shift 3
  local names=("$@")
  local joined
  joined="$(IFS=,; echo "${names[*]}")"
  (
    cd "$source"
    "$mvn" -q -o "-Dotc.demo.existing.keys=$keys" "-Dtest=$joined" test
  )
  T154_NAMES="$joined" T154_LABEL="$group" T154_EXPECTED="$expected" \
    python3 - "$source" <<'PY'
from pathlib import Path
from xml.etree import ElementTree as E
import os,sys
root=Path(sys.argv[1])/'target/surefire-reports'
names=os.environ['T154_NAMES'].split(',')
sums={k:0 for k in ('tests','failures','errors','skipped')}
for name in names:
    files=list(root.glob('TEST-*'+name+'.xml'))
    if len(files)!=1:
        raise SystemExit(f'T154_FAIL: missing or duplicate test report {name}')
    report=E.parse(files[0]).getroot()
    for k in sums:
        sums[k]+=int(report.attrib.get(k,'0'))
    print('T154_CASES',os.environ['T154_LABEL'],name,report.attrib.get('tests'))
expected=int(os.environ['T154_EXPECTED'])
if sums['tests'] != expected or any(sums[k]!=0 for k in ('failures','errors','skipped')):
    raise SystemExit(f'T154_FAIL: {os.environ["T154_LABEL"]} {sums}')
print('T154_REAL_BUSINESS_'+os.environ['T154_LABEL']+'_PASS '+str(sums))
PY
}
run_group "$order" "ORDER" 45 "${orderTests[@]}"
run_group "$trade" "TRADE" 52 "${tradeTests[@]}"
echo "T154_ORDER_TRADE_REAL_FUNCTIONAL_SMOKE_97_OF_97_PASS"
echo "T154_SCOPE: actual production domain and loopback Netty signed WAL tests,"
echo "T154_SCOPE: NOT an inter-container public trading API or HA READY assertion"