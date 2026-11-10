package com.app.dc.service.simulation;

import com.alibaba.fastjson2.JSON;
import com.alibaba.fastjson2.JSONObject;
import com.app.dc.po.TTbookOhlc;
import com.app.dc.po.backtest.BacktestParam;
import com.app.dc.service.simulation.runtime.ExecutionStressService;
import com.app.dc.service.simulation.runtime.StrategyCandidateRow;
import com.app.dc.service.simulation.runtime.VersionedBacktestRunner;
import com.app.dc.service.simulation.scene.DeepSeekSceneTimelineService;
import com.app.dc.signal.BuySellSignalFacade;
import com.app.dc.signal.StrategyParametersSupport;
import org.springframework.beans.factory.annotation.Value;

import java.lang.reflect.Field;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.security.MessageDigest;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Properties;

/** Offline existing-engine replay. No Spring startup, database, HTTP, optimizer or publication. */
public final class OfflineTemporalReplayCli {
    static void require(boolean condition, String message) {
        if (!condition) throw new IllegalArgumentException(message);
    }

    static String sha(byte[] bytes) throws Exception {
        StringBuilder result = new StringBuilder();
        for (byte value : MessageDigest.getInstance("SHA-256").digest(bytes)) {
            result.append(String.format("%02x", value & 0xff));
        }
        return result.toString();
    }

    static byte[] verified(Path path, String expected) throws Exception {
        byte[] bytes = Files.readAllBytes(path);
        require(expected != null && sha(bytes).equals(expected), "frozen artifact/input hash mismatch: " + path);
        return bytes;
    }

    static void inject(Object target, Class<?> owner, String name, Object value) throws Exception {
        Field field = owner.getDeclaredField(name);
        field.setAccessible(true);
        field.set(target, value);
    }

    static void configureValues(Object target, Class<?> owner, Properties properties,
                                Map<String, Object> effective) throws Exception {
        for (Field field : owner.getDeclaredFields()) {
            Value annotation = field.getAnnotation(Value.class);
            if (annotation == null) continue;
            String expression = annotation.value();
            require(expression.startsWith("${") && expression.endsWith("}"), "unsupported configuration expression");
            String body = expression.substring(2, expression.length() - 1);
            int separator = body.indexOf(':');
            require(separator > 0, "explicit engine configuration default required");
            String key = body.substring(0, separator);
            String text = properties.getProperty(key, body.substring(separator + 1));
            require(!text.contains("${"), "unresolved execution configuration: " + key);
            Object value;
            if (field.getType() == boolean.class) {
                require("true".equalsIgnoreCase(text) || "false".equalsIgnoreCase(text), "invalid execution boolean");
                value = Boolean.valueOf(text);
            } else if (field.getType() == double.class) value = Double.valueOf(text);
            else if (field.getType() == int.class) value = Integer.valueOf(text);
            else if (field.getType() == BigDecimal.class) value = new BigDecimal(text);
            else if (field.getType() == String.class) value = text;
            else throw new IllegalArgumentException("unsupported execution configuration field " + key);
            field.setAccessible(true);
            field.set(target, value);
            effective.put(key, value);
        }
    }

    static final class Engine {
        final BacktestSupportService support = new BacktestSupportService();
        final BacktestService legacy = new BacktestService();
        final BacktestMetricService metrics = new BacktestMetricService();
        final BacktestTradeService trades = new BacktestTradeService();
        final BuySellSignalFacade facade = new BuySellSignalFacade();
        final VersionedBacktestRunner runner = new VersionedBacktestRunner();
        final ExecutionStressService stress = new ExecutionStressService();
        final Map<String, Object> effective = new LinkedHashMap<String, Object>();

        Engine(Properties properties) throws Exception {
            configureValues(support, BacktestSupportService.class, properties, effective);
            configureValues(runner, VersionedBacktestRunner.class, properties, effective);
            configureValues(stress, ExecutionStressService.class, properties, effective);
            inject(legacy, BacktestService.class, "supportService", support);
            inject(runner, VersionedBacktestRunner.class, "legacyBacktestService", legacy);
            inject(runner, VersionedBacktestRunner.class, "supportService", support);
            inject(runner, VersionedBacktestRunner.class, "metricService", metrics);
            inject(runner, VersionedBacktestRunner.class, "tradeService", trades);
            inject(runner, VersionedBacktestRunner.class, "runtimeFacade", facade);
        }
    }

    static final class Replay {
        final StrategyCandidateRow candidate;
        final BacktestParam param;
        final List<TTbookOhlc> bars;
        final DeepSeekSceneTimelineService.Timeline timeline;
        final Map<String, Object> locked;
        final String sourceSha;

        Replay(JSONObject spec) throws Exception {
            require("offline_temporal_replay_v1".equals(spec.getString("schema")), "explicit replay schema required");
            String symbol = spec.getString("symbol"), scene = spec.getString("scene");
            require(symbol != null && symbol.matches("[A-Z0-9]+"), "explicit single symbol required");
            require(scene != null && scene.matches("trend|range|channel|breakout|reversal"), "explicit tradable scene required");
            LocalDate first = LocalDate.parse(spec.getString("beginDate"));
            LocalDate last = LocalDate.parse(spec.getString("endDate"));
            require(!last.isBefore(first), "invalid replay date order");
            if (spec.getBooleanValue("formalHoldout")) {
                require(first.equals(LocalDate.parse(spec.getString("primaryEndDate")).plusDays(1)), "holdout must follow primary period");
                require(java.time.temporal.ChronoUnit.DAYS.between(first, last) + 1 >= 62, "holdout cannot be shortened");
            }
            sourceSha = sha(new String(Files.readAllBytes(Paths.get(spec.getString("sourcePath"))),
                    StandardCharsets.UTF_8).replace("\r\n", "\n").getBytes(StandardCharsets.UTF_8));
            require(sourceSha.equals(spec.getString("sourceSha256")), "source changed before replay");
            verified(Paths.get(spec.getString("artifactPath")), spec.getString("artifactSha256"));
            JSONObject selected = spec.getJSONObject("lockedParameters");
            require(selected != null, "parameters must be explicitly locked, including an empty fixed-source map");
            locked = new LinkedHashMap<String, Object>(selected);
            candidate = new StrategyCandidateRow();
            candidate.strategyName = spec.getString("strategyName");
            candidate.strategyVersion = spec.getString("strategyVersion");
            candidate.scene = scene;
            candidate.category = "generated";
            candidate.runtimeType = "JAR";
            candidate.artifactUri = spec.getString("artifactPath");
            candidate.entryClass = spec.getString("entryClass");
            candidate.parametersJson = spec.getJSONObject("candidateParameters").toJSONString();
            candidate.payload = "{}";
            require(StrategyParametersSupport.resolveRuntimeParams(candidate.parametersJson, locked).equals(locked),
                    "locked parameters do not cover the actual runtime defaults");
            param = new BacktestParam();
            param.strategyName = candidate.strategyName;
            param.strategyVersion = candidate.strategyVersion;
            param.symbol = symbol;
            param.symbols = symbol;
            param.text = "15M";
            param.beginDate = first.toString();
            param.endDate = last.toString();
            param.initialCapital = new BigDecimal("10000");
            param.entryMakerFeeRatePct = new BigDecimal("0.02");
            param.exitTakerFeeRatePct = new BigDecimal("0.05");
            param.maxHoldBars = 0;
            param.ignoreSentimentGuard = true;
            param.allowMissingStageAnalysis = true;
            param.runtimeType = "JAR";
            param.scene = scene;
            param.strategyParams = new LinkedHashMap<String, Object>(locked);
            String barText = new String(verified(Paths.get(spec.getString("barsPath")),
                    spec.getString("barsSha256")), StandardCharsets.UTF_8);
            StringBuilder selectedBars = new StringBuilder();
            for (String line : barText.split("\\R")) {
                if (line.trim().isEmpty()) continue;
                String day = line.substring(0, 10);
                if (day.compareTo(first.toString()) >= 0 && day.compareTo(last.toString()) <= 0) selectedBars.append(line).append('\n');
            }
            bars = LocalResearchMarketData.loadBars(selectedBars.toString().getBytes(StandardCharsets.UTF_8), symbol);
            byte[] sceneBytes = verified(Paths.get(spec.getString("scenesPath")), spec.getString("scenesSha256"));
            List<DeepSeekSceneTimelineService.SceneRow> scenes = LocalResearchMarketData.loadScenes(sceneBytes);
            LocalResearchMarketData.requireSceneCoverage(scenes, first.toString(), last.toString());
            List<DeepSeekSceneTimelineService.SceneRow> selectedScenes = new ArrayList<DeepSeekSceneTimelineService.SceneRow>();
            for (DeepSeekSceneTimelineService.SceneRow row : scenes) {
                String day = row.runTime.substring(0, 10);
                if (day.compareTo(first.minusDays(1).toString()) >= 0 && day.compareTo(last.toString()) <= 0) selectedScenes.add(row);
            }
            timeline = DeepSeekSceneTimelineService.buildTimeline(selectedScenes, 13);
        }
    }

    static BacktestModels.BacktestResult run(Engine engine, Replay replay) throws Exception {
        return engine.runner.runSceneGated(replay.candidate, replay.param, replay.bars,
                replay.timeline.cursor(), new BacktestModels.SceneShadowMetrics());
    }

    public static void main(String[] args) throws Exception {
        require(args.length == 3, "expected frozen replay specification, execution properties, output file");
        require(ZoneOffset.UTC.equals(ZoneId.systemDefault().getRules().getOffset(Instant.now())), "UTC replay clock required");
        JSONObject spec = JSON.parseObject(new String(Files.readAllBytes(Paths.get(args[0])), StandardCharsets.UTF_8));
        Properties properties = new Properties();
        try (java.io.InputStream stream = Files.newInputStream(Paths.get(args[1]))) { properties.load(stream); }
        Engine engine = new Engine(properties);
        Replay replay = new Replay(spec);
        try {
            BacktestModels.BacktestResult result = run(engine, replay);
            BigDecimal adjusted = engine.stress.adjustedPnl(result);
            Map<String, Object> output = new LinkedHashMap<String, Object>();
            output.put("beginDate", replay.param.beginDate);
            output.put("endDate", replay.param.endDate);
            output.put("tradeCount", result.tradeCount);
            output.put("profitFactor", result.profitFactor);
            output.put("maxDrawdownPct", result.maxDrawdownPct);
            output.put("feeAdjustedPnl", adjusted);
            output.put("passed", LocalHoldoutReplay.passes(result, adjusted));
            output.put("lockedParameters", replay.locked);
            output.put("parameterPolicy", "frozen_pre_holdout_representative");
            output.put("sourceSha256", replay.sourceSha);
            output.put("artifactSha256", spec.getString("artifactSha256"));
            output.put("effectiveExecutionConfig", engine.effective);
            output.put("optimizerInvocations", 0);
            output.put("fitInvocations", 0);
            output.put("productionWrite", false);
            output.put("trades", result.tradeList);
            output.put("rejectReasonCounts", result.rejectReasonCounts);
            Files.write(Paths.get(args[2]), (JSON.toJSONString(output) + "\n").getBytes(StandardCharsets.UTF_8));
            System.out.println("OFFLINE_LOCKED_REPLAY_COMPLETE");
        } finally {
            engine.facade.unload(replay.candidate.strategyName, replay.candidate.strategyVersion);
        }
    }
}
