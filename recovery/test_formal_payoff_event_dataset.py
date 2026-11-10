import unittest
import numpy as np
import pandas as pd

from recovery.build_formal_payoff_event_dataset import sample_events


class FormalPayoffEventDatasetTest(unittest.TestCase):
    def frame(self):
        i = np.arange(14000)
        close = 100 + 2 * np.sin(i / 9.)
        return pd.DataFrame({'time': pd.date_range('2024-08-10', periods=len(i), freq='15min', tz='UTC'),
            'open': close - .1, 'high': close + .6, 'low': close - .6, 'close': close,
            'volume': 100 + i % 13})

    def events(self, frame):
        return [{'family': 'AuctionValueRejectionHypothesis', 'side': side, 'index': i,
                 'time': int(frame.iloc[i]['time'].timestamp() * 1000)}
                for i in range(200, len(frame), 16) for side in (1, -1)]

    def test_entire_potential_label_window_is_training_only_and_cannot_cross_a_gap(self):
        frame = self.frame().drop(index=2000).reset_index(drop=True)
        rows = sample_events(frame, self.events(frame))
        self.assertTrue(rows)
        for family, side, x, y, year, start, end in rows:
            self.assertLess(frame.iloc[start + 96]['time'], pd.Timestamp('2024-12-15', tz='UTC'))
            self.assertEqual(pd.Timedelta(minutes=(96 + 199) * 15),
                             frame.iloc[start + 96]['time'] - frame.iloc[start - 199]['time'])
            self.assertEqual(year, frame.iloc[end]['time'].year)
            self.assertLessEqual(end, start + 96)
            self.assertEqual(18, len(x))
            self.assertTrue(np.isfinite(y))

    def test_tampered_event_and_duplicate_are_rejected(self):
        frame = self.frame()
        event = self.events(frame)[0]
        with self.assertRaisesRegex(ValueError, 'identity'):
            sample_events(frame, [{**event, 'time': event['time'] + 1}])
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            sample_events(frame, [event, event])


if __name__ == '__main__':
    unittest.main()
