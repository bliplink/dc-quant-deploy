"""Freeze one OHLCV histogram proxy; never infer independence from mode/direction."""

import hashlib
import json
from pathlib import Path
import re

from recovery.strategy_recovery_common import atomic_write_json


VARIANTS = ((0, 1), (0, -1), (1, 1), (1, -1))


def source_file(indsvr_repo):
    return indsvr_repo / 'src/test/java/com/app/dc/service/strategy/research/OhlcvProfileProxyStrategy.java'


def frozen_source(native, symbol, scene, side, mode):
    if (not re.fullmatch(r'[A-Z0-9]+', symbol)
            or scene not in ('trend', 'range', 'channel', 'breakout', 'reversal')
            or type(side) is not int or type(mode) is not int or (mode, side) not in VARIANTS):
        raise ValueError('explicit scope and profile event/direction required')
    hypothesis = 'ovp1_' + ('value_reentry_' if mode == 0 else 'node_migration_') + ('long' if side > 0 else 'short')
    digest = hashlib.sha256(('ohlcv_profile_proxy_v1:' + symbol + ':' + scene + ':' + hypothesis).encode()).hexdigest()[:12]
    name = 'catalog_' + symbol.lower() + '_' + scene + '_' + digest
    source = native.replace('\r\n', '\n')
    replacements = {
        'package com.app.dc.service.strategy.research;': 'package com.app.dc.generated.autogen.' + name + '.v1;',
        'public class OhlcvProfileProxyStrategy extends LegacyLiveSignalAdapter': 'public class GeneratedStrategy extends LegacyLiveSignalAdapter',
        'private static final String STRATEGY_NAME = "research_ohlcv_profile_proxy";': 'private static final String STRATEGY_NAME = "' + name + '";',
        'private static final String SYMBOL = "BTCUSDT";': 'private static final String SYMBOL = "' + symbol + '";',
        'private static final int ENTRY_SIDE = 1;': 'private static final int ENTRY_SIDE = ' + str(side) + ';',
        'private static final int ENTRY_MODE = 0;': 'private static final int ENTRY_MODE = ' + str(mode) + ';',
    }
    for before, after in replacements.items():
        if source.count(before) != 1:
            raise ValueError('native profile export contract changed: ' + before)
        source = source.replace(before, after, 1)
    family = 'CatalogAtrExitOhlcvProfileProxyHypothesis'
    item = {'strategyName': name, 'sourceStrategyVersion': 'v1', 'symbol': symbol, 'scene': scene, 'text': '15m',
        'request': {'sourceRef': 'local-ohlcv-profile-proxy:20261111:' + hypothesis,
            'logicSummary': family + '; fixed128-completed-bar/32-bin OHLCV typical-price proxy; one auction mechanism; ATR14 stop1.5/profile target/ATR20 exits',
            'javaSourceBase64': '', 'parameterSchema': {}, 'defaultParameters': {}, 'optimizationProfile': {
                'fitWindowDays': 90 if scene == 'range' else 120,
                'validateWindowDays': 20 if scene in ('breakout', 'reversal') else 30,
                'forwardWindowDays': 10 if scene in ('breakout', 'reversal') else 14,
                'minSliceCount': 3, 'minForwardContribution': .20, 'objective': 'FEE_ADJUSTED_PROFIT_FIRST'}}}
    return source, item, {'hypothesis': hypothesis, 'family': family, 'side': side, 'mode': mode,
                         'mechanism_group': 'ohlcv_distribution_auction'}


def export_candidate(indsvr_repo, output_dir, symbol, scene, side, mode):
    source, item, descriptor = frozen_source(source_file(indsvr_repo).read_text(encoding='utf-8'), symbol, scene, side, mode)
    folder = output_dir / item['strategyName']
    expected = hashlib.sha256(source.encode('utf-8')).hexdigest()
    if folder.exists():
        if (hashlib.sha256((folder / 'GeneratedStrategy.java').read_bytes()).hexdigest() != expected
                or json.loads((folder / 'seed.json').read_text(encoding='utf-8')) != {'strategies': [item]}):
            raise ValueError('frozen profile source/seed changed')
    else:
        folder.mkdir(parents=True)
        (folder / 'GeneratedStrategy.java').write_text(source, encoding='utf-8', newline='\n')
        atomic_write_json(folder / 'seed.json', {'strategies': [item]})
        atomic_write_json(folder / 'frozen.json', dict(descriptor, strategy_name=item['strategyName'], source_sha256=expected,
            symbol=symbol, scene=scene, financial_validation_started=False, production_write=False))
    return folder, item, descriptor
