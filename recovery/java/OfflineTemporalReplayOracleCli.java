package com.app.dc.service.simulation;

import com.alibaba.fastjson2.JSON;
import com.alibaba.fastjson2.JSONObject;
import com.app.dc.service.simulation.runtime.StrategyBacktestTaskDao;
import com.app.dc.service.simulation.runtime.StrategyCandidateRow;
import com.app.dc.signal.BuySellSignalFacade;
import com.app.dc.signal.MarketSeriesRegistry;
import com.app.dc.signal.SignalContext;
import com.app.dc.signal.StrategyDefinition;
import com.app.dc.po.Signal;
import com.app.dc.po.Side;
import com.app.dc.po.TTbookOhlc;
import org.springframework.context.support.StaticApplicationContext;

import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Properties;

/** Training-only integration oracle against the existing LocalHoldoutReplay and publisher parameter helper. */
public final class OfflineTemporalReplayOracleCli {
    private static StrategyBacktestTaskDao candidateFixture(final StrategyCandidateRow candidate) {
        return (StrategyBacktestTaskDao) java.lang.reflect.Proxy.newProxyInstance(
                StrategyBacktestTaskDao.class.getClassLoader(), new Class<?>[]{StrategyBacktestTaskDao.class},
                (proxy, method, values) -> {
                    if (!"loadCandidate".equals(method.getName())) {
                        throw new UnsupportedOperationException("oracle forbids every task mutation: " + method.getName());
                    }
                    OfflineTemporalReplayCli.require(candidate.strategyName.equals(values[0])
                            && candidate.strategyVersion.equals(values[1]), "unexpected training-only candidate lookup");
                    return candidate;
                });
    }

    private static String publishParameters(StrategyCandidateRow candidate, Map<String, Object> selected) throws Exception {
        Class<?> publisherType = Class.forName("com.app.dc.service.simulation.runtime.StrategyAutoPublishService");
        Method resolver = null;
        for (Method method : publisherType.getDeclaredMethods()) {
            if ("resolveRuntimeParametersJson".equals(method.getName())) resolver = method;
        }
        OfflineTemporalReplayCli.require(resolver != null, "actual publisher parameter resolver is missing");
        resolver.setAccessible(true);
        Class<?> summaryType = resolver.getParameterTypes()[1];
        java.lang.reflect.Constructor<?> constructor = summaryType.getDeclaredConstructor();
        constructor.setAccessible(true);
        Object summary = constructor.newInstance();
        OfflineTemporalReplayCli.inject(summary, summaryType, "bestParamSetJson", JSON.toJSONString(selected));
        return (String) resolver.invoke(publisherType.getConstructor().newInstance(), candidate, summary);
    }

    private static void same(Object expected, Object actual, String field) {
        OfflineTemporalReplayCli.require(JSON.toJSONString(expected).equals(JSON.toJSONString(actual)),
                "actual-engine training replay differs: " + field);
    }

    private static Object signalFields(Signal signal) {
        if (signal == null || signal.side == null || signal.side == Side.NONE) return null;
        Map<String, Object> fields = new LinkedHashMap<String, Object>();
        fields.put("side", signal.side); fields.put("entry", signal.price);
        fields.put("stop", signal.stopPrice); fields.put("target", signal.takerPrice);
        fields.put("first", signal.firstStep); fields.put("step", signal.step);
        fields.put("fallbackTrigger", signal.underTriggerProfitPrice);
        fields.put("fallbackTake", signal.underTakerProfitPrice);
        return fields;
    }

    private static int verifyLiveLoading(OfflineTemporalReplayCli.Engine engine,
                                         OfflineTemporalReplayCli.Replay replay, String published) throws Exception {
        Class<?> liveType = Class.forName("com.app.dc.service.strategy.runtime.StrategyLiveRegistryRow");
        Object live = liveType.getConstructor().newInstance();
        for (String field : new String[]{"strategyName", "strategyVersion", "category", "scene", "runtimeType", "artifactUri", "entryClass"}) {
            liveType.getField(field).set(live, StrategyCandidateRow.class.getField(field).get(replay.candidate));
        }
        liveType.getField("parametersJson").set(live, published);
        StrategyDefinition liveDefinition = (StrategyDefinition) liveType.getMethod("toDefinition").invoke(live);
        same(replay.locked, liveDefinition.parameters, "actual live-row flat parameter parsing");
        BuySellSignalFacade liveFacade = new BuySellSignalFacade();
        BuySellSignalFacade referenceFacade = new BuySellSignalFacade();
        MarketSeriesRegistry liveSeries = new MarketSeriesRegistry(), referenceSeries = new MarketSeriesRegistry();
        int count = 0;
        try {
            liveFacade.load(liveDefinition);
            referenceFacade.load(replay.candidate.toDefinition(replay.locked));
            for (TTbookOhlc row : replay.bars) {
                org.ta4j.core.Bar bar = engine.legacy.toBar(row, engine.support.resolveDuration("15M"));
                liveSeries.appendBar("15M", replay.param.symbol, bar);
                referenceSeries.appendBar("15M", replay.param.symbol, bar);
                SignalContext a = SignalContext.backtest(replay.param.symbol, "15M", row, liveSeries.getSeries("15M", replay.param.symbol));
                a.indicatorSymbol = liveSeries.getIndicatorSymbol("15M"); a.marketSeriesRegistry = liveSeries;
                SignalContext b = SignalContext.backtest(replay.param.symbol, "15M", row, referenceSeries.getSeries("15M", replay.param.symbol));
                b.indicatorSymbol = referenceSeries.getIndicatorSymbol("15M"); b.marketSeriesRegistry = referenceSeries;
                Object actual = signalFields(liveFacade.evaluate(replay.candidate.strategyName, replay.candidate.strategyVersion, a));
                Object expected = signalFields(referenceFacade.evaluate(replay.candidate.strategyName, replay.candidate.strategyVersion, b));
                same(expected, actual, "publisher -> actual live row -> real runtime init -> all signal risk fields");
                if (actual != null) count++;
            }
        } finally {
            liveFacade.unload(replay.candidate.strategyName, replay.candidate.strategyVersion);
            referenceFacade.unload(replay.candidate.strategyName, replay.candidate.strategyVersion);
        }
        OfflineTemporalReplayCli.require(count > 0, "live parameter-flow fixture must produce actual signals");
        return count;
    }

    public static void main(String[] args) throws Exception {
        OfflineTemporalReplayCli.require(args.length == 3, "expected engineering spec, execution properties, audit output");
        JSONObject spec = JSON.parseObject(new String(Files.readAllBytes(Paths.get(args[0])), StandardCharsets.UTF_8));
        OfflineTemporalReplayCli.require(!spec.getBooleanValue("formalHoldout")
                && spec.getString("endDate").compareTo("2024-12-15") < 0, "oracle is restricted to training history");
        Properties properties = new Properties();
        try (java.io.InputStream stream = Files.newInputStream(Paths.get(args[1]))) { properties.load(stream); }
        OfflineTemporalReplayCli.Replay replay = new OfflineTemporalReplayCli.Replay(spec);
        OfflineTemporalReplayCli.Engine engine = new OfflineTemporalReplayCli.Engine(properties);
        StaticApplicationContext context = new StaticApplicationContext();
        try {
            BacktestModels.BacktestResult direct = OfflineTemporalReplayCli.run(engine, replay);
            OfflineTemporalReplayCli.inject(engine.legacy, BacktestService.class, "strategyBacktestTaskDao",
                    candidateFixture(replay.candidate));
            LocalResearchMarketData.install(engine.legacy, Paths.get(spec.getString("fixtureDir")),
                    replay.param.symbol, replay.param.text, replay.param.beginDate, replay.param.endDate,
                    spec.getString("barsSha256"), spec.getString("scenesSha256"));
            context.getBeanFactory().registerSingleton("existingVersionedRunner", engine.runner);
            context.getBeanFactory().registerSingleton("existingExecutionStress", engine.stress);
            context.refresh();
            Map<String, Object> reference = LocalHoldoutReplay.run(context, engine.legacy, replay.param, replay.param.beginDate);
            same(reference.get("tradeCount"), direct.tradeCount, "tradeCount");
            same(reference.get("profitFactor"), direct.profitFactor, "profitFactor");
            same(reference.get("maxDrawdownPct"), direct.maxDrawdownPct, "maxDrawdownPct");
            same(reference.get("feeAdjustedPnl"), engine.stress.adjustedPnl(direct), "feeAdjustedPnl");
            same(reference.get("passed"), LocalHoldoutReplay.passes(direct, engine.stress.adjustedPnl(direct)), "gate");
            same(reference.get("trades"), direct.tradeList, "all trade fields and fees");
            same(reference.get("rejectReasonCounts"), direct.rejectReasonCounts, "rejection accounting");
            String published = publishParameters(replay.candidate, replay.locked);
            same(new JSONObject(replay.locked), JSON.parseObject(published), "actual publisher selected parameters");
            int liveSignals = verifyLiveLoading(engine, replay, published);
            Map<String, Object> output = new LinkedHashMap<String, Object>();
            output.put("passed", true);
            output.put("tradeCount", direct.tradeCount);
            output.put("lockedParameters", replay.locked);
            output.put("sourceSha256", replay.sourceSha);
            output.put("effectiveExecutionConfig", engine.effective);
            output.put("reference", "unchanged_LocalHoldoutReplay");
            output.put("publisherParameterFunctionVerified", true);
            output.put("liveRegistryParameterParsingAndSignalsVerified", true);
            output.put("liveSignalCount", liveSignals);
            output.put("realDatabasePersistenceVerified", false);
            output.put("trainingOnly", true);
            output.put("engineeringSceneFixtureOnly", true);
            output.put("productionWrite", false);
            Files.write(Paths.get(args[2]), (JSON.toJSONString(output) + "\n").getBytes(StandardCharsets.UTF_8));
            System.out.println("OFFLINE_TEMPORAL_ORACLE_PASSED trades=" + direct.tradeCount);
        } finally {
            context.close();
            engine.facade.unload(replay.candidate.strategyName, replay.candidate.strategyVersion);
        }
    }
}
