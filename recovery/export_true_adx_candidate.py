"""Export one self-contained, genuinely repaired ADX policy; no model or financial access."""

import hashlib
import json
import re
from pathlib import Path

from recovery.strategy_recovery_common import atomic_write_json


VARIANTS = ((1, False), (-1, False), (1, True), (-1, True))


def source_file(indsvr_repo):
    return indsvr_repo / 'src/test/java/com/app/dc/service/strategy/research/TrueAdxRepairStrategy.java'


def frozen_source(native, symbol, scene, side, selective):
    if not re.fullmatch(r'[A-Z0-9]+', symbol) or scene not in ('trend', 'range', 'channel', 'breakout', 'reversal'):
        raise ValueError('explicit supported symbol and scene required')
    if type(side) is not int or side not in (-1, 1) or type(selective) is not bool:
        raise ValueError('one of four frozen directions required')
    hypothesis = 'ta1_' + ('selective_' if selective else '') + 'adx_directional_breakout_' + ('long' if side > 0 else 'short')
    digest = hashlib.sha256(('true_adx_repair_v1:' + symbol + ':' + scene + ':' + hypothesis).encode()).hexdigest()[:12]
    name = 'catalog_' + symbol.lower() + '_' + scene + '_' + digest
    source = native.replace('\r\n', '\n')
    replacements = {
        'package com.app.dc.service.strategy.research;': 'package com.app.dc.generated.autogen.' + name + '.v1;',
        'public class TrueAdxRepairStrategy extends LegacyLiveSignalAdapter': 'public class GeneratedStrategy extends LegacyLiveSignalAdapter',
        'private static final String STRATEGY_NAME = "research_true_adx_directional_long";': 'private static final String STRATEGY_NAME = "' + name + '";',
        'private static final String SYMBOL = "BTCUSDT";': 'private static final String SYMBOL = "' + symbol + '";',
        'private static final int ENTRY_SIDE = 1;': 'private static final int ENTRY_SIDE = ' + str(side) + ';',
        'private static final boolean SELECTIVE = false;': 'private static final boolean SELECTIVE = ' + str(selective).lower() + ';',
    }
    for before, after in replacements.items():
        if source.count(before) != 1:
            raise ValueError('native ADX export contract changed: ' + before)
        source = source.replace(before, after, 1)
    family = 'CatalogAtrExitTrueAdx' + ('Selective' if selective else 'Directional') + 'BreakoutHypothesis'
    item = {'strategyName': name, 'sourceStrategyVersion': 'v1', 'symbol': symbol, 'scene': scene, 'text': '15m',
        'request': {'sourceRef': 'local-true-adx-repair:20261110:' + hypothesis,
            'logicSummary': family + '; fixed Wilder DMI/ADX period14 threshold20; retained DI-gap8/12, ATR14 risk1.5/3, ATR20 explicit exits',
            'javaSourceBase64': '', 'parameterSchema': {}, 'defaultParameters': {}, 'optimizationProfile': {
                'fitWindowDays': 90 if scene == 'range' else 120,
                'validateWindowDays': 20 if scene in ('breakout', 'reversal') else 30,
                'forwardWindowDays': 10 if scene in ('breakout', 'reversal') else 14,
                'minSliceCount': 3, 'objective': 'FEE_ADJUSTED_PROFIT_FIRST'}}}
    return source, item, {'hypothesis': hypothesis, 'family': family, 'side': side, 'selective': selective,
                         'mechanism_group': 'wilder_adx_directional_breakout'}


def export_candidate(indsvr_repo, output_dir, symbol, scene, side, selective):
    native = source_file(indsvr_repo).read_text(encoding='utf-8')
    source, item, descriptor = frozen_source(native, symbol, scene, side, selective)
    folder = output_dir / item['strategyName']
    expected = hashlib.sha256(source.encode('utf-8')).hexdigest()
    if folder.exists():
        previous = (folder / 'GeneratedStrategy.java').read_text(encoding='utf-8')
        if hashlib.sha256(previous.encode('utf-8')).hexdigest() != expected:
            raise ValueError('frozen true ADX source changed')
        if json.loads((folder / 'seed.json').read_text(encoding='utf-8')) != {'strategies': [item]}:
            raise ValueError('frozen true ADX metadata changed')
    else:
        folder.mkdir(parents=True)
        (folder / 'GeneratedStrategy.java').write_text(source, encoding='utf-8', newline='\n')
        atomic_write_json(folder / 'seed.json', {'strategies': [item]})
        atomic_write_json(folder / 'frozen.json', dict(descriptor, strategy_name=item['strategyName'],
            source_sha256=expected, symbol=symbol, scene=scene, production_write=False, financial_validation_started=False))
    return folder, item, descriptor
