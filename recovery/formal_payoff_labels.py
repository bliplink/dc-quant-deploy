"""Versioned, training-only ATR-path labels with formal arithmetic and costs.

This is still a censored individual-event proxy, not a scene/portfolio backtest.
Historical label helpers and their frozen datasets are deliberately unchanged.
"""

import math
from decimal import Decimal, ROUND_HALF_UP


LABEL_SCHEMA = 'formal_arithmetic_atr_exit_payoff_v1'
HORIZON = 96


def rounded(value, digits):
    return Decimal(str(float(value))).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)


def adjusted_return(entry, exit_price, side, capital=10000.):
    """Formal return rounded to 6dp, plus actual default stress notional costs."""
    if side not in (-1, 1) or not all(math.isfinite(v) and v > 0 for v in (entry, exit_price, capital)):
        raise ValueError('positive finite prices/capital and explicit side required')
    gross = (entry - exit_price) / entry if side < 0 else (exit_price - entry) / entry
    raw = rounded(gross - (.02 + .05) / 100., 6)
    qty = rounded(capital / entry, 6)
    entry_notional = qty * rounded(entry, 6)
    exit_notional = qty * rounded(exit_price, 6)
    stress = (entry_notional * Decimal('.0004')).quantize(Decimal('0.0000000001'), rounding=ROUND_HALF_UP)
    stress += (exit_notional * Decimal('.0005')).quantize(Decimal('0.0000000001'), rounding=ROUND_HALF_UP)
    stress = stress.quantize(Decimal('0.00000001'), rounding=ROUND_HALF_UP)
    return float(raw) - float(stress) / capital


def trailing_stop(entry, close, stop, side, first, step):
    profit = ((entry - close) / entry if side < 0 else (close - entry) / entry) * 100.
    if profit > first:
        steps = math.floor((profit - first) / step)
        protected_pct = first + step * (float(steps) - 1.)
        protected = entry * (1. + protected_pct / 100. if side > 0 else 1. - protected_pct / 100.)
        return max(stop, protected) if side > 0 else min(stop, protected)
    return stop


def path_label(prices, index, atr, side, horizon=HORIZON):
    if side not in (-1, 1) or not math.isfinite(atr) or atr <= 0:
        raise ValueError('positive ATR and explicit direction required')
    if index < 0 or horizon < 2 or index + horizon >= len(prices):
        return None
    entry = float(prices[index, 3])
    if not math.isfinite(entry) or entry <= 0:
        raise ValueError('positive finite entry required')
    fill = prices[index + 1]
    if (side > 0 and fill[2] > entry) or (side < 0 and fill[1] < entry):
        return None
    stop, take = entry - side * 1.5 * atr, entry + side * 3. * atr
    if stop <= 0 or take <= 0:
        return None
    pct = atr / entry * 100.
    first, step = max(.5, 2. * pct), .5 * pct
    # Explicit fallback trigger=first+step cannot precede the first-step branch.
    for j in range(index + 2, index + horizon + 1):
        _, high, low, close = prices[j]
        if not all(math.isfinite(v) and v > 0 for v in (high, low, close)):
            raise ValueError('invalid future OHLC in training-only label window')
        hit_stop = low <= stop if side > 0 else high >= stop
        hit_take = high >= take if side > 0 else low <= take
        if hit_stop or hit_take:
            exit_price = stop if hit_stop else take
            return adjusted_return(entry, exit_price, side), j, 'stop' if hit_stop else 'take'
        stop = trailing_stop(entry, close, stop, side, first, step)
    return None
