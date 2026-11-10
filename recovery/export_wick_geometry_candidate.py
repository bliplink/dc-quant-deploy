"""Self-contained frozen OHLCV wick-geometry repair; no finance or model access."""

import hashlib
import json
import re
from pathlib import Path

from recovery.strategy_recovery_common import atomic_write_json


VARIANTS = (1, -1)


def source_file(indsvr_repo):
    return indsvr_repo / 'src/test/java/com/app/dc/service/strategy/research/WickGeometryRepairStrategy.java'


def frozen_source(native, symbol, scene, side):
    if (not re.fullmatch(r'[A-Z0-9]+', symbol)
            or scene not in ('trend', 'range', 'channel', 'breakout', 'reversal')
            or type(side) is not int or side not in VARIANTS):
        raise ValueError('explicit supported scope and direction required')
    hypothesis = 'wgr1_wick_rejection_confirmation_' + ('long' if side > 0 else 'short')
    digest = hashlib.sha256(('wick_geometry_repair_v1:' + symbol + ':' + scene + ':' + hypothesis).encode()).hexdigest()[:12]
    name = 'catalog_' + symbol.lower() + '_' + scene + '_' + digest
    source = native.replace('\r\n', '\n')
    replacements = {
        'package com.app.dc.service.strategy.research;': 'package com.app.dc.generated.autogen.' + name + '.v1;',
        'public class WickGeometryRepairStrategy extends LegacyLiveSignalAdapter': 'public class GeneratedStrategy extends LegacyLiveSignalAdapter',
        'private static final String STRATEGY_NAME = "research_wick_geometry_long";': 'private static final String STRATEGY_NAME = "' + name + '";',
        'private static final String SYMBOL = "BTCUSDT";': 'private static final String SYMBOL = "' + symbol + '";',
        'private static final int ENTRY_SIDE = 1;': 'private static final int ENTRY_SIDE = ' + str(side) + ';',
    }
    for before, after in replacements.items():
        if source.count(before) != 1:
            raise ValueError('native wick export contract changed: ' + before)
        source = source.replace(before, after, 1)
    family = 'CatalogAtrExitWickGeometryRepairHypothesis'
    item = {'strategyName': name, 'sourceStrategyVersion': 'v1', 'symbol': symbol, 'scene': scene, 'text': '15m',
        'request': {'sourceRef': 'local-wick-geometry-repair:20261110:' + hypothesis,
            'logicSummary': family + '; fixed45pct wick rejection, mirrored55pct/45pct close, next-bar confirmation; retained actual ATR14 risk0.75/1.5 and ATR20 exits',
            'javaSourceBase64': '', 'parameterSchema': {}, 'defaultParameters': {}, 'optimizationProfile': {
                'fitWindowDays': 90 if scene == 'range' else 120,
                'validateWindowDays': 20 if scene in ('breakout', 'reversal') else 30,
                'forwardWindowDays': 10 if scene in ('breakout', 'reversal') else 14,
                'minSliceCount': 3, 'objective': 'FEE_ADJUSTED_PROFIT_FIRST'}}}
    return source, item, {'hypothesis': hypothesis, 'family': family, 'side': side,
                         'mechanism_group': 'wick_rejection_confirmation'}


def export_candidate(indsvr_repo, output_dir, symbol, scene, side):
    source, item, descriptor = frozen_source(source_file(indsvr_repo).read_text(encoding='utf-8'), symbol, scene, side)
    folder = output_dir / item['strategyName']
    expected = hashlib.sha256(source.encode('utf-8')).hexdigest()
    if folder.exists():
        if hashlib.sha256((folder / 'GeneratedStrategy.java').read_text(encoding='utf-8').encode('utf-8')).hexdigest() != expected:
            raise ValueError('frozen wick source changed')
        if json.loads((folder / 'seed.json').read_text(encoding='utf-8')) != {'strategies': [item]}:
            raise ValueError('frozen wick seed changed')
    else:
        folder.mkdir(parents=True)
        (folder / 'GeneratedStrategy.java').write_text(source, encoding='utf-8', newline='\n')
        atomic_write_json(folder / 'seed.json', {'strategies': [item]})
        atomic_write_json(folder / 'frozen.json', dict(descriptor, strategy_name=item['strategyName'], source_sha256=expected,
            symbol=symbol, scene=scene, financial_validation_started=False, production_write=False))
    return folder, item, descriptor
