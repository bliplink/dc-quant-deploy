from datetime import datetime, timezone
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch


MEASURE = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/measure-mac-demo-robot.py'))
GENERATION = 'mac-demo-20261113-134411'
ZERO = '0001-01-01T00:00:00Z'


class RobotMeasureLifecycleTest(unittest.TestCase):
    def voter(self, ident, service, **overrides):
        row = dict(ident=ident, name=f'{GENERATION}-{service}-a-hostready',
                   created='2026-11-13T05:44:00Z', started='2026-11-13T06:29:00Z',
                   finished='2026-11-13T06:28:00Z', running=True)
        row.update(overrides)
        return row

    def select(self, rows):
        def docker(arguments, **options):
            if arguments[1] == 'ps':
                return ''.join(f"{row['ident']} {row['name']}\n" for row in rows)
            if '.Created' in arguments[3]:
                return ''.join(f"{r['ident']} {r['created']} {r['started']} {r['finished']} {str(r['running']).lower()}\n"
                               for r in rows)
            return ''.join(f"{r['ident']} {r['started']} {r['finished']}\n" for r in rows)
        with patch.object(MEASURE['subprocess'], 'check_output', side_effect=docker):
            return MEASURE['voter_containers'](
                GENERATION, datetime(2026, 11, 13, 6, 30, tzinfo=timezone.utc),
                datetime(2026, 11, 13, 6, 35, tzinfo=timezone.utc))

    def test_running_restarted_container_ignores_previous_finish_time(self):
        rows = [self.voter('order', 'order'), self.voter('trade', 'trade')]
        window, current = self.select(rows)
        self.assertEqual({'order': ['order'], 'trade': ['trade']}, window)
        self.assertEqual(['order', 'trade'], current)

    def test_prior_incarnation_logs_remain_candidates_after_a_later_restart(self):
        rows = [self.voter('order', 'order', started='2026-11-13T06:40:00Z'),
                self.voter('trade', 'trade', started='2026-11-13T06:40:00Z',
                           finished='2026-11-13T06:45:00Z', running=False)]
        self.assertEqual({'order': ['order'], 'trade': ['trade']}, self.select(rows)[0])

    def test_future_never_started_and_fully_retired_voters_are_excluded(self):
        rows = [self.voter('order', 'order', finished=ZERO), self.voter('trade', 'trade', finished=ZERO)]
        for ident, changes in [('future', {'created': '2026-11-13T06:40:00Z'}),
                               ('never', {'started': ZERO, 'finished': ZERO, 'running': False}),
                               ('retired', {'running': False})]:
            rows.append(self.voter(ident, 'order', name=f'{GENERATION}-order-b-hostready-retained-{ident}', **changes))
        self.assertEqual({'order': ['order'], 'trade': ['trade']}, self.select(rows)[0])

    def test_missing_trade_process_window_still_fails(self):
        with self.assertRaisesRegex(RuntimeError, 'Missing physical'):
            self.select([self.voter('order', 'order'), self.voter('trade', 'trade', running=False)])


if __name__ == '__main__':
    unittest.main()
