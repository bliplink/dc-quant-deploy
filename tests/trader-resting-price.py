#!/usr/bin/env python3
"""Choose a non-crossing BUY limit price from a demo market snapshot.

Reads a public MDSvr JSON response on stdin. No API keys or network access.
The result is only a candidate price; the exchange's price bands still apply.
"""
from decimal import Decimal, InvalidOperation, ROUND_DOWN
import json
import sys


def choose_resting_bid(snapshot, tick="0.1", discount="0.005"):
    try:
        entries = ((snapshot.get("data") or {}).get("orderBook") or {}).get("NoMDEntries") or []
        bids = [
            Decimal(str(row["MDEntryPx"]))
            for row in entries if str(row.get("MDEntryType")) == "0"
        ]
        bids = [price for price in bids if price.is_finite() and price > 0]
        if not bids:
            raise ValueError("no positive bid found in demo market snapshot")
        best_bid = max(bids)
        unit = Decimal(tick)
        margin = Decimal(discount)
        if unit <= 0 or margin <= 0 or margin >= 1:
            raise ValueError("invalid price tick or resting margin")
        candidate = ((best_bid * (Decimal(1) - margin)) / unit).to_integral_value(
            rounding=ROUND_DOWN
        ) * unit
        if candidate <= 0 or candidate >= best_bid:
            raise ValueError("could not calculate a non-crossing positive limit price")
        return format(candidate, "f")
    except (InvalidOperation, KeyError, TypeError) as exc:
        raise ValueError("invalid public market snapshot fields") from exc


if __name__ == "__main__":
    try:
        print(choose_resting_bid(json.load(sys.stdin)))
    except (ValueError, json.JSONDecodeError) as exc:
        print("Could not determine isolated-test resting limit: " + str(exc), file=sys.stderr)
        raise SystemExit(2)
