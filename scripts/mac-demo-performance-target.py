"""Owner-selected first-stage targets, separate from financial integrity checks."""
import math


OPERATIONS_PER_SECOND = 1000
P99_MILLISECONDS = 20


def complete_latency(distribution, samples):
    p99 = distribution.get('p99')
    return (samples > 0 and distribution.get('samples') == samples
            and isinstance(p99, (float, int)) and math.isfinite(p99)
            and 0 <= p99 <= P99_MILLISECONDS)


def execution_target(aggregate, seconds, integrity_passed, qualified_window=True):
    samples = aggregate.get('sent_orders', 0)
    throughput = aggregate.get('observed_window_execution_rate', 0)
    checks = {
        'qualified_window': qualified_window is True,
        'integrity': integrity_passed is True,
        'sustained_window': seconds >= 60,
        'all_requests_and_fills_accounted': (
            aggregate.get('all_accepted_final_receipts_pass') is True
            and aggregate.get('generator_accounting_pass') is True
            and aggregate.get('scheduler_drops') == 0
            and samples == aggregate.get('planned_orders') == aggregate.get('final_executions')),
        'actual_in_window_final_trade_rate': math.isfinite(throughput) and throughput >= OPERATIONS_PER_SECOND,
        'client_final_receipt_p99': complete_latency(aggregate.get('client_fill_ms', {}), samples),
        # Include load-generator dispatch delay so a delayed generator cannot
        # hide queueing by starting the latency clock after the delay.
        'scheduled_final_receipt_p99': complete_latency(aggregate.get('scheduled_fill_ms', {}), samples),
    }
    return {'passed': all(checks.values()), 'target_per_second': OPERATIONS_PER_SECOND,
            'target_p99_ms': P99_MILLISECONDS, 'unit': 'Actual final trade receipts per second',
            'checks': checks, 'observed_per_second': throughput,
            'tail_final_receipts_after_window': aggregate.get('final_executions', 0)
                - aggregate.get('fills_inside_offered_window', 0)}


def order_cancel_target(phase, transport):
    rows = phase.get('records', [])
    attempted_cycles = [row for row in rows if row.get('outcome') != 'ORDER_BUSY_RETRYABLE']
    samples = len(attempted_cycles)
    seconds = phase.get('window_seconds', 0)
    fields = ('new_inside_window', 'cancel_inside_window')
    counted = bool(attempted_cycles) and all(isinstance(row.get(key), bool) for row in attempted_cycles for key in fields)
    inside = sum(row.get(key) is True for row in attempted_cycles for key in fields)
    rate = inside / seconds if seconds > 0 and counted else 0
    checks = {
        'native_tcp': transport == 'tcp',
        'integrity': phase.get('passed') is True,
        'sustained_window': seconds >= 60,
        'native_window_statuses_observed': counted,
        'all_operations_completed': bool(rows) and all(row.get('passed') is True for row in rows),
        'successful_command_rate': math.isfinite(rate) and rate >= OPERATIONS_PER_SECOND,
        'new_status_p99': complete_latency(phase.get('place_new_ms', {}), samples),
        'cancel_terminal_p99': complete_latency(phase.get('cancel_terminal_ms', {}), samples),
    }
    return {'passed': all(checks.values()), 'target_per_second': OPERATIONS_PER_SECOND,
            'target_p99_ms': P99_MILLISECONDS, 'unit': 'Place plus cancel commands per second',
            'observed_per_second': rate, 'checks': checks,
            'window_commands': inside if counted else None,
            'late_commands': sum(row.get(key) is False for row in attempted_cycles for key in fields) if counted else None,
            'note': 'A complete place/cancel cycle is two commands, not an actual trade.'}
