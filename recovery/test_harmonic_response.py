"""Independent feature/label-boundary checks; training forecast diagnostics are not financial qualification."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from recovery import research_harmonic_response as research
from recovery.verify_fit_only_risk_contract import sha


def quotes_from_returns(returns):
    closes = 1000 * np.exp(np.r_[0., np.cumsum(returns)])
    opens = np.r_[closes[0], closes[:-1]]
    quotes = np.column_stack((opens, np.maximum(opens, closes) + 1,
        np.minimum(opens, closes) - 1, closes, np.full(len(closes), 100.)))
    times = research.milliseconds('2023-01-01') + np.arange(len(closes)) * research.PERIOD
    return times, quotes


def independent_feature(values):
    centered = [float(v) - sum(values) / 64 for v in values]
    selected, strongest = 0, -1.
    for bin_no in range(2, 9):
        real = sum(centered[j] * np.cos(-2 * np.pi * bin_no * j / 64) for j in range(64))
        imaginary = sum(centered[j] * np.sin(-2 * np.pi * bin_no * j / 64) for j in range(64))
        power = real * real + imaginary * imaginary
        if power > strongest: selected, strongest = bin_no, power
    projected = sum(centered[j] * np.cos(2 * np.pi * selected * (j - 64 - h) / 64)
        for j in range(64) for h in range(8)) / 32
    concentration = 2 * strongest / (64 * sum(v * v for v in centered))
    return selected, projected, concentration


class HarmonicResponseTrainingTest(unittest.TestCase):
    def test_full_harmonic_cycle_is_exact_zero_for_every_phase_and_amplitude(self):
        j = np.arange(64)
        windows = np.asarray([amplitude * np.cos(2 * np.pi * 8 * j / 64 + phase) + drift
            for amplitude in (1e-9, .001, .1) for phase in np.linspace(0, 2*np.pi, 17)
            for drift in (0., .01)])
        actual = research.spectral_features(windows)
        np.testing.assert_array_equal(actual['bin'], np.full(len(windows),8))
        self.assertTrue(np.all(actual['valid']))
        np.testing.assert_array_equal(actual['projection'],np.zeros(len(windows)))
        # The separate complex convolution oracle agrees up to cancellation error;
        # the exact expected zero follows from the roots-of-unity identity.
        for row in windows[::13]:
            expected = independent_feature(row)
            self.assertEqual(8,expected[0]); self.assertAlmostEqual(0.,expected[1],places=13)

    def test_full_cycle_has_no_fittable_response_or_indicative_hurdle(self):
        j=np.arange(64)
        windows=np.asarray([.001*np.cos(2*np.pi*8*j/64+phase) for phase in np.linspace(0,6,96)])
        x=research.spectral_features(windows)['projection']; y=np.linspace(-.02,.02,len(x))
        model=research.fit_response(x,y)
        self.assertIsNone(model)
        audit=research.evaluate_response(x,y,model)
        self.assertFalse(audit['model_available']); self.assertEqual(0,audit['indicative_hurdle_exceedances'])
        self.assertEqual(0,audit['financial_qualified_candidates'])

    def test_non_full_cycle_projection_is_not_zeroed_by_a_magnitude_filter(self):
        j=np.arange(64)
        for bin_no in range(2,8):
            raw=1e-12*np.cos(2*np.pi*bin_no*j/64+.31)
            actual=research.spectral_features(raw[None,:]); expected=independent_feature(raw)
            self.assertEqual(bin_no,actual['bin'][0]); self.assertNotEqual(0.,actual['projection'][0])
            self.assertAlmostEqual(expected[1]/1e-12,actual['projection'][0]/1e-12,places=12)

    def test_pure_cosine_and_sine_match_separate_direct_projection(self):
        j = np.arange(64)
        for a, b in ((.001, 0), (0, .002)):
            raw = a * np.cos(2 * np.pi * 3 * j / 64) + b * np.sin(2 * np.pi * 3 * j / 64)
            actual = research.spectral_features(raw[None, :]); expected = independent_feature(raw)
            self.assertTrue(actual['valid'][0]); self.assertEqual(expected[0], actual['bin'][0])
            self.assertAlmostEqual(expected[1], actual['projection'][0], places=13)
            self.assertAlmostEqual(1., actual['concentration'][0], places=12)

    def test_sixty_four_random_return_windows_match_complex_convolution_oracle(self):
        generator = np.random.default_rng(2026111119)
        windows = generator.normal(0, .002, (64, 64))
        result = research.spectral_features(windows)
        for i, row in enumerate(windows):
            expected = independent_feature(row)
            self.assertEqual(expected[0], result['bin'][i])
            self.assertAlmostEqual(expected[1], result['projection'][i], places=12)
            self.assertAlmostEqual(expected[2], result['concentration'][i], places=12)

    def test_mean_drift_is_removed_and_excluded_frequencies_remain_in_full_energy(self):
        j = np.arange(64)
        raw = .001 * np.cos(2 * np.pi * 4 * j / 64) + .002 * np.cos(2 * np.pi * j / 64)
        actual = research.spectral_features(raw[None, :])
        shifted = research.spectral_features((raw + .01)[None, :])
        self.assertEqual(4, actual['bin'][0]); self.assertAlmostEqual(.2, actual['concentration'][0], places=12)
        np.testing.assert_allclose(actual['projection'], shifted['projection'], atol=1e-13, rtol=0)
        self.assertTrue(actual['valid'][0])  # Features are diagnostic, NOT a modified old strategy signal.

    def test_invalid_shapes_nonfinite_and_flat_energy_do_not_become_signals(self):
        for data in (np.ones(64), np.ones((3, 63)), np.full((2, 64), np.nan)):
            with self.assertRaises(ValueError): research.spectral_features(data)
        actual = research.spectral_features(np.zeros((2, 64)))
        self.assertFalse(np.any(actual['valid'])); np.testing.assert_array_equal(actual['projection'], [0, 0])

    def test_feature_at_an_origin_does_not_depend_on_future_prices(self):
        generator = np.random.default_rng(4); times, quotes = quotes_from_returns(generator.normal(0, .001, 320))
        before = research.sample_features(times, quotes)
        changed = quotes.copy()
        changed[201:, :4] *= 2
        after = research.sample_features(times, changed)
        keep = before['origin_index'] <= 192
        np.testing.assert_array_equal(before['origin_index'][keep], after['origin_index'][keep])
        for name in ('projection','concentration','bin'):
            np.testing.assert_allclose(before[name][keep], after[name][keep], atol=0, rtol=0)

    def test_origins_follow_utc_grid_labels_are_exactly_eight_completed_bars(self):
        times, quotes = quotes_from_returns(np.random.default_rng(5).normal(0, .001, 240))
        actual = research.sample_features(times, quotes)
        self.assertTrue(len(actual['origin_index']))
        self.assertTrue(np.all(actual['origin_time'] % (8 * research.PERIOD) == 0))
        np.testing.assert_array_equal(actual['label_end_time'] - actual['origin_time'], np.full(len(actual['origin_time']),8*research.PERIOD))
        indices = actual['origin_index']
        np.testing.assert_allclose(actual['label'], np.log(quotes[indices+8,3])-np.log(quotes[indices,3]), atol=0, rtol=0)

    def test_missing_bars_cannot_be_bridged_by_features_or_labels(self):
        times, quotes = quotes_from_returns(np.random.default_rng(6).normal(0, .001, 240))
        times[121:] += research.PERIOD
        actual = research.sample_features(times, quotes); indices = actual['origin_index']
        self.assertGreater(actual['skipped_gap_spans'],0)
        self.assertFalse(np.any((indices - 64 < 121) & (indices + 8 >= 121)))

    def test_zero_current_volume_and_bad_geometry_are_not_filled(self):
        times, quotes = quotes_from_returns(np.random.default_rng(7).normal(0, .001, 240))
        quotes[128,4] = 0
        actual = research.sample_features(times, quotes)
        self.assertNotIn(128,actual['origin_index']); self.assertGreater(actual['skipped_nonpositive_origin_volume'],0)
        quotes[30,1] = 1
        with self.assertRaises(ValueError): research.sample_features(times, quotes)

    def test_chunk_size_does_not_change_any_observed_feature_or_label(self):
        times, quotes = quotes_from_returns(np.random.default_rng(8).normal(0,.001,320))
        first=research.sample_features(times,quotes,chunk_rows=1)
        second=research.sample_features(times,quotes,chunk_rows=2048)
        for name in ('origin_index','origin_time','label_end_time','bin','projection','concentration','label'):
            np.testing.assert_allclose(first[name],second[name],rtol=0,atol=0)

    def test_slope_uses_fixed_zero_intercept_and_predeclared_shrinkage(self):
        x=np.linspace(-.02,.02,96); y=.75*x
        model=research.fit_response(x,y)
        self.assertAlmostEqual(.75*96/(96+12),model['beta'],places=14)
        self.assertEqual(96,model['samples']); self.assertGreater(model['descriptive_slope_error'],0)

    def test_insufficient_or_zero_energy_fit_is_not_falsely_available(self):
        self.assertIsNone(research.fit_response(np.ones(31),np.ones(31)))
        self.assertIsNone(research.fit_response(np.zeros(64),np.ones(64)))
        with self.assertRaises(ValueError): research.fit_response(np.ones(64),np.ones(64),pseudo=0)
        with self.assertRaises(ValueError): research.fit_response(np.ones(64),np.full(64,np.nan))

    def test_negative_and_zero_labels_are_kept_without_clipping(self):
        x=np.linspace(-.02,.02,96); y=np.r_[np.full(40,-.01),np.zeros(16),np.full(40,.01)]
        model=research.fit_response(x,y)
        self.assertEqual(40,model['negative_labels']); self.assertEqual(16,model['zero_labels'])
        self.assertEqual(40,model['positive_labels']); self.assertEqual(-.01,model['minimum_label'])

    def test_hurdle_selection_uses_frozen_prediction_not_audit_labels(self):
        model=dict(beta=1.,descriptive_slope_error=0.)
        x=np.array([.0024,np.nextafter(.0024,np.inf),-.003])
        first=research.evaluate_response(x,np.array([1.,-1.,0.]),model)
        second=research.evaluate_response(x,np.array([-100.,100.,2.]),model)
        self.assertEqual(2,first['indicative_hurdle_exceedances'])
        self.assertEqual(first['indicative_hurdle_exceedances'],second['indicative_hurdle_exceedances'])
        self.assertEqual(1,first['predicted_long']); self.assertEqual(1,first['predicted_short'])
        self.assertFalse(first['label_is_trading_pnl']); self.assertEqual(0,first['financial_qualified_candidates'])

    def test_fit_boundary_labels_are_purged_and_audit_never_refits(self):
        start=research.milliseconds('2024-01-01')
        fit_times=start-np.arange(64,0,-1)*8*research.PERIOD
        audit_times=start+np.arange(64)*8*research.PERIOD
        samples=dict(origin_time=np.r_[fit_times,audit_times],label_end_time=np.r_[fit_times,audit_times]+8*research.PERIOD,
            bin=np.full(128,3),projection=np.linspace(-.01,.01,128),concentration=np.full(128,.2),
            label=np.linspace(-.001,.001,128),skipped_gap_spans=0,skipped_nonpositive_origin_volume=0,skipped_degenerate_energy=0)
        first=research.diagnostic(samples)
        altered=copy.deepcopy(samples); altered['label'][64:]*=-100
        second=research.diagnostic(altered)
        self.assertEqual(1,first['purged_fit_boundary_labels'])
        self.assertEqual(63,first['fit_samples']); self.assertEqual(64,first['audit_samples'])
        self.assertEqual(first['frequency_models'][1]['frozen_fit_model'],second['frequency_models'][1]['frozen_fit_model'])
        self.assertNotEqual(first['frequency_models'][1]['audit'],second['frequency_models'][1]['audit'])
        self.assertFalse(first['financial_validation_read'])

    def test_input_hash_cutoff_membership_and_geometry_are_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'BTCUSDT-15m.tsv'
            path.write_text('2023-01-01 00:00:00.000000\t100\t101\t99\t100\t1\n',encoding='utf-8')
            record=dict(bars_sha256=sha(path),rows=1,last_time='2023-01-01 00:00:00.000000')
            times,values=research.load_training_bars(path,record,research.milliseconds('2024-12-15'))
            self.assertEqual((1,5),values.shape)
            with self.assertRaises(ValueError): research.load_training_bars(path,dict(record,bars_sha256='bad'),research.milliseconds('2024-12-15'))
            with self.assertRaises(ValueError): research.load_training_bars(path,record,research.milliseconds('2023-01-01'))
            with self.assertRaises(ValueError): research.load_training_bars(path,dict(record,rows=2),research.milliseconds('2024-12-15'))

    def test_protocol_declares_training_only_not_relabelled_strategy_qualification(self):
        policy=json.loads(Path(research.__file__).with_name('harmonic_response_training_protocol_20261111.json').read_text())
        self.assertEqual('training_forecast_diagnostic_only',policy['purpose'])
        self.assertEqual('2024-12-15',policy['training_end_exclusive'])
        self.assertEqual('2024-01-01',policy['fit_end_exclusive']); self.assertEqual('2024-01-01',policy['audit_begin'])
        self.assertEqual(.0024,policy['forecast_hurdle_log_return'])
        self.assertFalse(policy['financial_validation_read']); self.assertFalse(policy['production_write'])
        self.assertEqual(0,policy['financial_qualified_candidates']); self.assertEqual(0,policy['server_or_llm_calls'])


if __name__=='__main__': unittest.main()
