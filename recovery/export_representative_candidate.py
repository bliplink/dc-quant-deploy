"""Freeze a catalog signal as self-contained Java source for the formal SIMSvr engine."""

import argparse
import hashlib
import json
import re
from pathlib import Path


def java_mask(text):
    """Keep offsets/braces while hiding comments, strings and character literals."""
    token = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', re.S)
    return token.sub(lambda match: ''.join('\n' if char == '\n' else ' '
                                          for char in match.group()), text)


def declaration(source, name, interface=False):
    mask = java_mask(source)
    kind = 'interface' if interface else 'class'
    match = re.search(r'^    (?:static\s+)?(?:(?:final|abstract)\s+)?' + kind
                      + r'\s+' + re.escape(name) + r'\b[^\{]*\{', mask, re.M)
    if not match:
        raise ValueError('research declaration not found: ' + name)
    depth = 1
    index = match.end()
    while depth and index < len(mask):
        depth += (mask[index] == '{') - (mask[index] == '}')
        index += 1
    if depth:
        raise ValueError('unbalanced research declaration: ' + name)
    return source[match.start():index]


def exit_policy_contract_version(research_source):
    setup = java_mask(declaration(research_source, 'Setup'))
    if 'EXIT_POLICY_SCHEMA_VERSION' not in setup:
        return 0  # Explicit historical source contract, output stays byte-identical.
    match = re.search(r'\bEXIT_POLICY_SCHEMA_VERSION\s*=\s*(\d+)\s*;', setup)
    if not match or match.group(1) != '1':
        raise ValueError('unsupported explicit exit policy source contract')
    return 1


def candidate_source(research_source, catalog_row, symbol, strategy_name, version='v1'):
    family = catalog_row['family']
    parameters = json.loads(catalog_row['parameters'])
    blocks = []
    current = family
    while current:
        block = declaration(research_source, current)
        blocks.append(block)
        parent = re.search(r'\bextends\s+(\w+)', java_mask(block).split('{', 1)[0])
        current = parent.group(1) if parent else None
    constructor = re.search(r'\b' + re.escape(family) + r'\s*\(([^)]*)\)', java_mask(blocks[0]))
    if not constructor:
        raise ValueError('signal constructor not found: ' + family)
    values = []
    for parameter in constructor.group(1).split(','):
        data_type, name = parameter.strip().split()
        if data_type == 'String' and name == 'name':
            values.append(json.dumps(catalog_row['hypothesis']))
        elif name in parameters:
            values.append(json.dumps(parameters[name]))
        else:
            raise ValueError('unresolved frozen constructor parameter: ' + parameter)
    expression = 'new ' + family + '(' + ', '.join(values) + ')'
    math_begin = research_source.index('    static Setup atrSetup(')
    math_end = research_source.index('    static final class ResearchResult', math_begin)
    support = declaration(research_source, 'Hypothesis', interface=True) + '\n' \
        + '\n'.join(reversed(blocks)) + '\n' + research_source[math_begin:math_end]
    if not re.fullmatch(r'[A-Z0-9]+', symbol):
        raise ValueError('invalid candidate symbol')
    if not re.fullmatch(r'v[1-9][0-9]*', version):
        raise ValueError('invalid candidate version')
    package = 'com.app.dc.generated.autogen.' + strategy_name + '.' + version
    header = '''package PACKAGE;
import java.math.BigDecimal;
import java.time.ZoneOffset;
import java.util.*;
import com.app.dc.fix.message.MarketDataSnapshotFullRefresh;
import com.app.dc.po.OCType;
import com.app.dc.po.Side;
import com.app.dc.po.Signal;
import com.app.dc.signal.IndicatorSymbol;
import com.app.dc.signal.LegacyLiveSignalAdapter;
import org.ta4j.core.BarSeries;

/** Frozen catalog signal. Only its selected implementation and mathematical helpers are embedded. */
public class GeneratedStrategy extends LegacyLiveSignalAdapter {
    private static final Hypothesis HYPOTHESIS = EXPRESSION;
    @Override
    public Signal onBars(MarketDataSnapshotFullRefresh newKline, IndicatorSymbol indicatorSymbol) {
        Signal signal = new Signal();
        String symbol = newKline.getSecurityID();
        if (!"SYMBOL".equals(symbol)) return signal;
        IndicatorSymbol.IndicatorVar variable = indicatorSymbol.getIndicator(symbol);
        if (variable == null || variable.series == null) return signal;
        final BarSeries series = variable.series;
        if (series.getBarCount() < HYPOTHESIS.warmupBars()) return signal;
        // ta4j 0.15 can retain beginIndex=0 after evicting old bars. Its visible
        // first index must come from endIndex and retained bar count.
        final int begin = Math.max(series.getBeginIndex(),
                series.getEndIndex() - series.getBarCount() + 1);
        // A view avoids copying the full series on each bar and preserves window-local warmup.
        List<Bar> bars = new AbstractList<Bar>() {
            @Override public int size() { return series.getBarCount(); }
            @Override public Bar get(int index) {
                org.ta4j.core.Bar bar = series.getBar(begin + index);
                return new Bar(bar.getEndTime().toInstant().toEpochMilli(),
                    bar.getOpenPrice().doubleValue(), bar.getHighPrice().doubleValue(),
                    bar.getLowPrice().doubleValue(), bar.getClosePrice().doubleValue(),
                    bar.getVolume().doubleValue());
            }
        };
        Setup setup = HYPOTHESIS.setup(bars, bars.size() - 1);
        if (setup == null || !setup.valid()) return signal;
        signal.symbol = symbol;
        signal.text = newKline.getInfo3();
        signal.side = setup.side > 0 ? Side.BUY : Side.SELL;
        signal.ocType = OCType.OPEN;
        signal.orderType = "LIMIT";
        signal.price = BigDecimal.valueOf(setup.entry);
        signal.stopPrice = BigDecimal.valueOf(setup.stop);
        signal.takerPrice = BigDecimal.valueOf(setup.target);
        signal.firstStep = BigDecimal.valueOf(0.5);
        signal.step = BigDecimal.valueOf(0.2);
        signal.underTriggerProfitPrice = BigDecimal.valueOf(0.8);
        signal.underTakerProfitPrice = BigDecimal.valueOf(0.5);
        signal.strategyName = "STRATEGY";
        return signal;
    }
'''
    header = header.replace('PACKAGE', package).replace('EXPRESSION', expression) \
        .replace('SYMBOL', symbol).replace('STRATEGY', strategy_name)
    if exit_policy_contract_version(research_source) == 1:
        for field, literal, attribute in (
                ('firstStep', '0.5', 'firstStepPct'), ('step', '0.2', 'stepPct'),
                ('underTriggerProfitPrice', '0.8', 'fallbackTriggerPct'),
                ('underTakerProfitPrice', '0.5', 'fallbackTakePct')):
            header = header.replace('signal.' + field + ' = BigDecimal.valueOf(' + literal + ');',
                                    'signal.' + field + ' = BigDecimal.valueOf(setup.exitPolicy.' + attribute + ');')
    return header + support + '\n}\n'


def export_candidate(campaign_dir, indsvr_repo, output_dir, symbol, scene, hypothesis, version='v1'):
    manifest = json.loads((campaign_dir / 'campaign.json').read_text(encoding='utf-8'))
    row = next(item for item in manifest['catalog'] if item['hypothesis'] == hypothesis)
    research = indsvr_repo / 'src/test/java/com/app/dc/service/strategy/research/StrategyResearchBatchCli.java'
    text = research.read_text(encoding='utf-8')
    source_hash = hashlib.sha256(research.read_bytes()).hexdigest()
    if source_hash != manifest['source_sha256']['StrategyResearchBatchCli']:
        raise ValueError('frozen research source changed')
    identifier = hashlib.sha256((symbol + ':' + scene + ':' + hypothesis).encode()).hexdigest()[:12]
    name = 'catalog_' + symbol.lower() + '_' + scene + '_' + identifier
    source = candidate_source(text, row, symbol, name, version)
    source_hash = hashlib.sha256(source.encode('utf-8')).hexdigest()
    seed_item = {'strategyName': name, 'sourceStrategyVersion': version, 'symbol': symbol,
                 'scene': scene, 'text': '15m', 'request': {
                     'sourceRef': 'local-catalog:20261110:' + hypothesis,
                     'logicSummary': row['family'] + '; frozen parameters ' + row['parameters'],
                     'javaSourceBase64': '', 'parameterSchema': {},
                     'defaultParameters': {}, 'optimizationProfile': {
                         'fitWindowDays': 90 if scene == 'range' else 120,
                         'validateWindowDays': 20 if scene in ('breakout', 'reversal') else 30,
                         'forwardWindowDays': 10 if scene in ('breakout', 'reversal') else 14,
                         'objective': 'FEE_ADJUSTED_PROFIT_FIRST'}}}
    output = output_dir / name
    if output.exists():
        existing = (output / 'GeneratedStrategy.java').read_text(encoding='utf-8')
        if hashlib.sha256(existing.encode('utf-8')).hexdigest() != source_hash:
            raise ValueError('frozen candidate source changed: ' + name)
        return output, name
    output.mkdir(parents=True)
    (output / 'GeneratedStrategy.java').write_text(source, encoding='utf-8', newline='\n')
    (output / 'seed.json').write_text(json.dumps({'strategies': [seed_item]}, indent=2), encoding='utf-8')
    (output / 'frozen.json').write_text(json.dumps({
        'strategy_name': name, 'strategy_version': version,
        'hypothesis': hypothesis, 'family': row['family'],
        'parameters': json.loads(row['parameters']), 'symbol': symbol, 'scene': scene,
        'source_sha256': source_hash, 'source_hash_contract': 'utf8_lf',
        'formal_qualified': False, 'production_write': False,
        'manifest_sha256': hashlib.sha256((campaign_dir / 'campaign.json').read_bytes()).hexdigest(),
    }, indent=2), encoding='utf-8')
    return output, name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign-dir', type=Path, required=True)
    parser.add_argument('--indsvr-repo', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--symbol', required=True)
    parser.add_argument('--scene', required=True)
    parser.add_argument('--hypothesis', required=True)
    parser.add_argument('--candidate-version', default='v1')
    args = parser.parse_args()
    output, name = export_candidate(args.campaign_dir, args.indsvr_repo, args.output_dir,
                                    args.symbol, args.scene, args.hypothesis, args.candidate_version)
    print(json.dumps({'strategy': name, 'directory': str(output)}))


if __name__ == '__main__':
    main()
