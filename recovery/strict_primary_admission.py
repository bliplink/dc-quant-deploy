"""Read-only adjudication of existing primary outputs; never replay or mutate financial data."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


MINIMUM_FORWARD_CONTRIBUTION = Decimal('0.20')


def number(value, name):
    if value is None or isinstance(value, bool):
        raise ValueError('missing or invalid primary metric: ' + name)
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError('invalid primary metric: ' + name) from error
    if not parsed.is_finite():
        raise ValueError('nonfinite primary metric: ' + name)
    return parsed


def adjudicate_primary(result, profile=None):
    """Keep the established 20% floor when a raw runner result leaves its DTO default at zero.

    LocalBacktestCli divides fee-adjusted forward by totalPnl to six decimals,
    HALF_UP. Its null-only default cannot distinguish an unfilled BigDecimal.ZERO
    field from an intentional policy. The real optimization default and server
    publication policy remain 0.20. Higher declared requirements stay higher.
    """
    profile = profile or {}
    required = MINIMUM_FORWARD_CONTRIBUTION
    for owner, value in (('result', result.get('minForwardContribution')),
                         ('profile', profile.get('minForwardContribution'))):
        if value is not None:
            parsed = number(value, owner + '.minForwardContribution')
            if parsed < 0:
                raise ValueError('negative forward contribution requirement')
            required = max(required, parsed)
    metrics = {key: number(result.get(key), key) for key in (
        'tradeCount', 'profitFactor', 'maxDrawdownPct', 'feeAdjustedValidatePnl',
        'feeAdjustedForwardPnl', 'totalPnl')}
    if metrics['tradeCount'] != metrics['tradeCount'].to_integral_value() or metrics['maxDrawdownPct'] < 0:
        raise ValueError('invalid count or drawdown')
    ratio = (metrics['feeAdjustedForwardPnl'] / metrics['totalPnl']).quantize(
        Decimal('0.000001'), rounding=ROUND_HALF_UP) if metrics['totalPnl'] > 0 else Decimal(0)
    reason = 'qualified'
    checks = (
        (result.get('executionModelVersion') == 'v4_non_overlapping_walk_forward', 'realistic_backtest_missing'),
        (result.get('oosPass') == 1 and not isinstance(result.get('oosPass'), bool), 'oos_not_passed'),
        (metrics['tradeCount'] >= 20, 'too_few_trades'),
        (metrics['profitFactor'] >= Decimal('1.20'), 'profit_factor_too_low'),
        (metrics['maxDrawdownPct'] <= Decimal('0.15'), 'drawdown_too_high'),
        (metrics['feeAdjustedValidatePnl'] > 0, 'fee_adjusted_validate_not_positive'),
        (metrics['feeAdjustedForwardPnl'] > 0, 'fee_adjusted_forward_not_positive'),
        (ratio >= required, 'forward_contribution_too_low'),
    )
    for passed, failure in checks:
        if not passed:
            reason = failure
            break
    return {'qualified': reason == 'qualified', 'reason': reason,
            'required_forward_contribution': str(required), 'forward_contribution_ratio': str(ratio),
            'raw_result_min_forward_contribution': result.get('minForwardContribution'),
            'financial_outputs_modified': False, 'financial_replay_performed': False}


def require_primary_admission(result, profile=None):
    audit = adjudicate_primary(result, profile)
    if not audit['qualified']:
        raise ValueError('strict existing primary qualification failed: ' + audit['reason'])
    return audit
