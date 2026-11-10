"""Export the predeclared causal signed-runs policy; two directions are one mechanism group."""
import hashlib
import json
from pathlib import Path
import re

from recovery.strategy_recovery_common import atomic_write_json

VARIANTS = (1, -1)


def source_file(indsvr_repo):
    return indsvr_repo / 'src/test/java/com/app/dc/service/strategy/research/RunsClusteringStrategy.java'


def frozen_source(native, symbol, scene, side):
    if (not re.fullmatch(r'[A-Z0-9]+', symbol) or scene not in ('trend', 'range', 'channel', 'breakout', 'reversal')
            or type(side) is not int or side not in VARIANTS):
        raise ValueError('explicit symbol/scene/direction required')
    hypothesis = 'rc1_signed_runs_' + ('long' if side > 0 else 'short')
    digest = hashlib.sha256(('runs_clustering_v1:' + symbol + ':' + scene + ':' + hypothesis).encode()).hexdigest()[:12]
    name = 'catalog_' + symbol.lower() + '_' + scene + '_' + digest
    source = native.replace('\r\n', '\n')
    replacements = {
        'package com.app.dc.service.strategy.research;': 'package com.app.dc.generated.autogen.' + name + '.v1;',
        'public class RunsClusteringStrategy extends LegacyLiveSignalAdapter': 'public class GeneratedStrategy extends LegacyLiveSignalAdapter',
        'private static final String STRATEGY_NAME = "research_runs_clustering";': 'private static final String STRATEGY_NAME = "' + name + '";',
        'private static final String SYMBOL = "BTCUSDT";': 'private static final String SYMBOL = "' + symbol + '";',
        'private static final int ENTRY_SIDE = 1;': 'private static final int ENTRY_SIDE = ' + str(side) + ';',
    }
    for before, after in replacements.items():
        if source.count(before) != 1: raise ValueError('runs export contract changed: ' + before)
        source = source.replace(before, after, 1)
    family = 'CatalogAtrExitRunsClusteringHypothesis'
    item = {'strategyName': name, 'sourceStrategyVersion': 'v1', 'symbol': symbol, 'scene': scene, 'text': '15m',
        'request': {'sourceRef': 'local-runs-clustering:20261111:' + hypothesis,
            'logicSummary': family + '; fixed64 completed return signs; zeros removed; conditional binary-run count Z first-cross below-2 with11 signs of each direction; current sign direction; ATR14 stop1.5/take3/ATR20 EMS',
            'javaSourceBase64': '', 'parameterSchema': {}, 'defaultParameters': {}, 'optimizationProfile': {
                'fitWindowDays': 90 if scene == 'range' else 120,
                'validateWindowDays': 20 if scene in ('breakout', 'reversal') else 30,
                'forwardWindowDays': 10 if scene in ('breakout', 'reversal') else 14,
                'minSliceCount': 3, 'minForwardContribution': .20, 'objective': 'FEE_ADJUSTED_PROFIT_FIRST'}}}
    return source, item, {'hypothesis': hypothesis, 'family': family, 'side': side,
                         'mechanism_group': 'conditional_signed_runs_clustering'}


def export_candidate(indsvr_repo, output_dir, symbol, scene, side):
    source, item, descriptor = frozen_source(source_file(indsvr_repo).read_text(encoding='utf-8'), symbol, scene, side)
    folder = output_dir / item['strategyName']; digest = hashlib.sha256(source.encode('utf-8')).hexdigest()
    if folder.exists():
        if (hashlib.sha256((folder / 'GeneratedStrategy.java').read_bytes()).hexdigest() != digest
                or json.loads((folder / 'seed.json').read_text(encoding='utf-8')) != {'strategies': [item]}):
            raise ValueError('frozen source/seed changed')
    else:
        folder.mkdir(parents=True)
        (folder / 'GeneratedStrategy.java').write_text(source, encoding='utf-8', newline='\n')
        atomic_write_json(folder / 'seed.json', {'strategies': [item]})
        atomic_write_json(folder / 'frozen.json', dict(descriptor, strategy_name=item['strategyName'], source_sha256=digest,
            symbol=symbol, scene=scene, financial_validation_started=False, production_write=False))
    return folder, item, descriptor
