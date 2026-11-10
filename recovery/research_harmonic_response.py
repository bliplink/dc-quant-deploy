"""Training-only harmonic response diagnosis; never a strategy/financial qualification."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import numpy as np

from recovery.run_directional_clock_parallel import extra_slot_resources
from recovery.run_directional_clock_batch import require_hashes
from recovery.run_fit_risk_catalog_batch import exclusive_batch, write_status
from recovery.verify_fit_only_risk_contract import sha

WINDOW, HORIZON, PERIOD = 64, 8, 900000
BINS = np.arange(2, 9)
EXPECTED_DATES = ('2022-01-01', '2024-01-01', '2024-01-01', '2024-12-15')


def milliseconds(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        raise ValueError('original naive UTC training timestamp required')
    return int(parsed.replace(tzinfo=timezone.utc).timestamp() * 1000)


def validate_quotes(times, quotes):
    if (times.ndim != 1 or quotes.shape != (len(times), 5) or len(times) == 0
            or not np.all(np.isfinite(quotes)) or np.any(np.diff(times) <= 0)
            or np.any(quotes[:, :4] <= 0) or np.any(quotes[:, 4] < 0)
            or np.any(quotes[:, 1] < np.maximum(quotes[:, 0], quotes[:, 3]))
            or np.any(quotes[:, 2] > np.minimum(quotes[:, 0], quotes[:, 3]))):
        raise ValueError('finite valid OHLCV and strictly increasing UTC times required')


def load_training_bars(path, record, cutoff):
    if sha(path) != record['bars_sha256']:
        raise ValueError('original training file digest changed')
    times, values = [], []
    with path.open(encoding='utf-8', newline='') as stream:
        for row in csv.reader(stream, delimiter='\t'):
            if len(row) != 6:
                raise ValueError('original six-column training OHLCV required')
            at = milliseconds(row[0])
            if at >= cutoff:
                raise ValueError('financial validation or later row forbidden')
            times.append(at); values.append([float(value) for value in row[1:]])
    times, quotes = np.asarray(times, dtype=np.int64), np.asarray(values, dtype=np.float64)
    validate_quotes(times, quotes)
    if (len(times) != record['rows'] or times[-1] != milliseconds(record['last_time'])
            or sha(path) != record['bars_sha256']):
        raise ValueError('training membership changed while reading')
    return times, quotes


def spectral_features(windows):
    windows = np.asarray(windows, dtype=np.float64)
    if windows.ndim != 2 or windows.shape[1] != WINDOW or not np.all(np.isfinite(windows)):
        raise ValueError('finite rows of exactly64 observed returns required')
    centered = windows - np.mean(windows, axis=1, keepdims=True)
    energy = np.sum(centered * centered, axis=1)
    spectrum = np.fft.rfft(centered, axis=1)[:, BINS]
    power = spectrum.real * spectrum.real + spectrum.imag * spectrum.imag
    offsets = np.argmax(power, axis=1); index = np.arange(len(windows))
    selected = BINS[offsets]; coefficient = spectrum[index, offsets]
    angles = 2 * np.pi * selected[:, None] * (WINDOW + np.arange(HORIZON)) / WINDOW
    projection = (coefficient.real * np.sum(np.cos(angles), axis=1)
        - coefficient.imag * np.sum(np.sin(angles), axis=1)) * (2.0 / WINDOW)
    # Roots of unity sum to exactly zero over an integer number of full periods.
    # Do not fit a response to floating-point cancellation residue (bin8 here).
    projection[(selected * HORIZON) % WINDOW == 0] = 0.0
    concentration = np.divide(2 * power[index, offsets], WINDOW * energy,
        out=np.zeros(len(windows)), where=energy > 0)
    if not (np.all(np.isfinite(energy)) and np.all(np.isfinite(projection)) and np.all(np.isfinite(concentration))):
        raise ValueError('nonfinite spectral calculation forbidden')
    valid = energy > 0
    return dict(bin=selected, projection=projection, concentration=concentration, valid=valid)


def sample_features(times, quotes, chunk_rows=2048):
    validate_quotes(times, quotes)
    if chunk_rows < 1: raise ValueError('positive bounded chunk required')
    closes = quotes[:, 3]; returns = np.diff(np.log(closes))
    origins = np.flatnonzero(times % (HORIZON * PERIOD) == 0)
    origins = origins[(origins >= WINDOW) & (origins + HORIZON < len(times))]
    gaps = np.r_[0, np.cumsum(np.diff(times) != PERIOD)]
    contiguous = gaps[origins + HORIZON] == gaps[origins - WINDOW]
    gap_count = int(np.sum(~contiguous)); origins = origins[contiguous]
    volume = quotes[origins, 4] > 0
    zero_volume_count = int(np.sum(~volume)); origins = origins[volume]
    keys = ('origin_index', 'origin_time', 'label_end_time', 'bin', 'projection', 'concentration', 'label')
    output = {key: [] for key in keys}; degenerate = 0
    for begin in range(0, len(origins), chunk_rows):
        subset = origins[begin:begin + chunk_rows]
        windows = returns[subset[:, None] - WINDOW + np.arange(WINDOW)]
        features = spectral_features(windows); mask = features['valid']; degenerate += int(np.sum(~mask))
        used = subset[mask]
        columns = (used, times[used], times[used + HORIZON], features['bin'][mask],
            features['projection'][mask], features['concentration'][mask],
            np.log(closes[used + HORIZON]) - np.log(closes[used]))
        for key, value in zip(keys, columns): output[key].append(value)
    for key in keys:
        output[key] = np.concatenate(output[key]) if output[key] else np.asarray([],
            dtype=np.int64 if key in keys[:4] else np.float64)
    output['skipped_gap_spans'] = gap_count
    output['skipped_nonpositive_origin_volume'] = zero_volume_count
    output['skipped_degenerate_energy'] = degenerate
    return output


def fit_response(x, y, pseudo=12, minimum=32):
    x, y = np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)
    if (x.shape != y.shape or x.ndim != 1 or not np.all(np.isfinite(x))
            or not np.all(np.isfinite(y)) or pseudo != 12 or minimum != 32):
        raise ValueError('fixed finite one-feature response fit required')
    n = len(x); xx = float(np.sum(x * x))
    if not np.isfinite(xx): raise ValueError('nonfinite fit energy forbidden')
    if n < minimum or xx <= 0:
        return None
    beta = float(np.sum(x * y) / xx) * n / (n + pseudo)
    residual = y - beta * x
    error = float(np.sqrt(np.sum(residual * residual) / (n - 1) / xx))
    if not np.isfinite(beta) or not np.isfinite(error): raise ValueError('nonfinite fitted response forbidden')
    return dict(samples=n, beta=beta, descriptive_slope_error=error,
        positive_labels=int(np.sum(y > 0)), negative_labels=int(np.sum(y < 0)),
        zero_labels=int(np.sum(y == 0)), minimum_label=float(np.min(y)), maximum_label=float(np.max(y)))


def evaluate_response(x, y, model):
    x, y = np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)
    if x.shape != y.shape or not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
        raise ValueError('finite aligned audit forecasts and labels required')
    if not len(x) or model is None:
        return dict(samples=len(x), model_available=model is not None,
            indicative_hurdle_exceedances=0, financial_qualified_candidates=0)
    predicted = model['beta'] * x
    hurdle = .0024 + 2 * np.abs(x) * model['descriptive_slope_error']
    selected = np.abs(predicted) > hurdle
    zero_mse = float(np.mean(y * y)); model_mse = float(np.mean((y - predicted) ** 2))
    count = int(np.sum(selected))
    return dict(samples=len(x), model_available=True,
        zero_forecast_mean_squared_log_error=zero_mse, model_mean_squared_log_error=model_mse,
        relative_mean_squared_log_error_improvement=(1 - model_mse / zero_mse) if zero_mse > 0 else None,
        indicative_hurdle_exceedances=count, predicted_long=int(np.sum(selected & (predicted > 0))),
        predicted_short=int(np.sum(selected & (predicted < 0))),
        directional_future_log_return_mean_selected=float(np.mean(np.sign(predicted[selected]) * y[selected])) if count else None,
        positive_labels=int(np.sum(y > 0)), negative_labels=int(np.sum(y < 0)), zero_labels=int(np.sum(y == 0)),
        financial_qualified_candidates=0, label_is_trading_pnl=False)


def diagnostic(samples):
    times, ends = samples['origin_time'], samples['label_end_time']
    fit_begin, fit_end, audit_begin, cutoff = map(milliseconds, EXPECTED_DATES)
    fit = (times >= fit_begin) & (times < fit_end) & (ends < fit_end)
    audit = (times >= audit_begin) & (ends < cutoff)
    purged = (times >= fit_begin) & (times < fit_end) & (ends >= fit_end)
    if np.any(ends[audit] >= cutoff) or np.any(ends[fit] >= fit_end):
        raise ValueError('future-label boundary crossed')
    records = []
    for bin_no in BINS:
        fit_mask, audit_mask = fit & (samples['bin'] == bin_no), audit & (samples['bin'] == bin_no)
        model = fit_response(samples['projection'][fit_mask], samples['label'][fit_mask])
        records.append(dict(bin=int(bin_no), frozen_fit_model=model,
            fit=evaluate_response(samples['projection'][fit_mask], samples['label'][fit_mask], model),
            audit=evaluate_response(samples['projection'][audit_mask], samples['label'][audit_mask], model),
            audit_old_concentration_threshold_window_count=int(np.sum(audit_mask & (samples['concentration'] >= .40)))))
    return dict(fit_samples=int(np.sum(fit)), audit_samples=int(np.sum(audit)), purged_fit_boundary_labels=int(np.sum(purged)),
        skipped_gap_spans=samples['skipped_gap_spans'], skipped_nonpositive_origin_volume=samples['skipped_nonpositive_origin_volume'],
        skipped_degenerate_energy=samples['skipped_degenerate_energy'], frequency_models=records,
        audit_indicative_hurdle_exceedances=sum(r['audit']['indicative_hurdle_exceedances'] for r in records),
        financial_qualified_candidates=0, financial_validation_read=False, server_or_llm_calls=0, production_write=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path, required=True)
    parser.add_argument('--protocol', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    for name in ('input_dir', 'protocol', 'output_dir'): setattr(args, name, getattr(args, name).resolve())
    policy = json.loads(args.protocol.read_text(encoding='utf-8'))
    expected = json.loads(Path(__file__).with_name('harmonic_response_training_protocol_20261111.json').read_text(encoding='utf-8'))
    if (policy != expected or tuple(policy[k] for k in ('fit_begin','fit_end_exclusive','audit_begin','training_end_exclusive')) != EXPECTED_DATES
            or policy.get('purpose') != 'training_forecast_diagnostic_only' or policy.get('financial_validation_read') is not False
            or policy.get('return_window') != WINDOW or policy.get('projection_bars') != HORIZON
            or policy.get('frequency_bins') != BINS.tolist() or policy.get('ridge_pseudo_samples') != 12
            or policy.get('forecast_hurdle_log_return') != .0024 or policy.get('minimum_fit_samples_per_bin') != 32
            or policy.get('sampling_stride_bars') != HORIZON or policy.get('bar_milliseconds') != PERIOD
            or policy.get('descriptive_uncertainty_multiple') != 2
            or policy.get('old_concentration_threshold_diagnostic_only') != .40
            or policy.get('no_loss_label_clipping_or_selection') is not True
            or policy.get('financial_qualified_candidates') != 0 or policy.get('server_or_llm_calls') != 0
            or policy.get('production_write') is not False):
        raise ValueError('predeclared training-only protocol required')
    if any(os.environ.get(k) != '1' for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS')):
        raise ValueError('single-threaded diagnostic environment required')
    ready_path = args.input_dir / 'READY.json'; ready = json.loads(ready_path.read_text(encoding='utf-8'))
    if ready.get('purpose') != 'training_only' or ready.get('train_end_exclusive') != EXPECTED_DATES[-1] or len(ready.get('files',{})) != 10:
        raise ValueError('original ten-symbol training-only input required')
    if args.output_dir.exists(): raise ValueError('preserve original diagnostic attempt; fresh output required')
    critical = {str(p): sha(p) for p in Path(__file__).parent.glob('*.py')}
    critical.update({str(p):sha(p) for p in (args.protocol,ready_path,Path(np.__file__),Path(np.fft.__file__),Path(sys.executable))})
    data = {str(args.input_dir/(s+'-15m.tsv')):r['bars_sha256'] for s,r in ready['files'].items()}
    require_hashes(data)
    args.output_dir.mkdir(parents=True)
    with exclusive_batch(args.output_dir):
        write_status(args.output_dir/'manifest.json',dict(schema='harmonic_response_training_diagnostic_run_v2',
            critical_sha256=critical,data_sha256=data,protocol_sha256=sha(args.protocol),numpy_version=np.__version__,
            python_version=sys.version,projection_label_is_trading_pnl=False,financial_validation_read=False,production_write=False))
        manifest_hash=sha(args.output_dir/'manifest.json'); records={}
        def guard(symbol):
            resources=extra_slot_resources(args.output_dir,3072)
            while not resources['ready']:
                write_status(args.output_dir/'status.json',dict(state='WAITING_FOR_TRAINING_DIAGNOSTIC_RESOURCES',
                    symbol=symbol,completed=len(records),total=10,resources=resources,financial_validation_read=False,production_write=False))
                time.sleep(10); resources=extra_slot_resources(args.output_dir,3072)
            require_hashes(critical)
            write_status(args.output_dir/'status.json',dict(state='RUNNING_TRAINING_DIAGNOSTIC',
                symbol=symbol,completed=len(records),total=10,financial_validation_read=False,production_write=False))
        try:
            for symbol, record in sorted(ready['files'].items()):
                guard(symbol)
                times, quotes=load_training_bars(args.input_dir/(symbol+'-15m.tsv'),record,milliseconds(EXPECTED_DATES[-1]))
                report=diagnostic(sample_features(times,quotes))
                report.update(symbol=symbol,manifest_sha256=manifest_hash,bars_sha256=record['bars_sha256'])
                path=args.output_dir/(symbol+'.json');write_status(path,report);records[symbol]=sha(path)
                del times,quotes
                print('HARMONIC_RESPONSE_TRAINING',symbol,'fit',report['fit_samples'],'audit',report['audit_samples'],
                    'forecast_hurdles',report['audit_indicative_hurdle_exceedances'],'not trading qualification',flush=True)
            require_hashes(critical);require_hashes(data)
            write_status(args.output_dir/'TRAINING_DIAGNOSTIC_COMPLETE.json',dict(manifest_sha256=manifest_hash,completed=10,
                symbol_report_sha256=records,financial_validation_read=False,financial_qualified_candidates=0,production_write=False))
            write_status(args.output_dir/'status.json',dict(state='COMPLETE',completed=10,total=10,
                financial_validation_read=False,financial_qualified_candidates=0,production_write=False))
        except Exception as error:
            write_status(args.output_dir/'FAILED.json',dict(completed=len(records),error=str(error),production_write=False));raise


if __name__ == '__main__': main()
