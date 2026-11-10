package com.app.dc.service.simulation;

import com.alibaba.fastjson2.JSON;
import com.alibaba.fastjson2.JSONObject;
import com.app.dc.po.TTbookOhlc;
import com.app.dc.po.backtest.BacktestParam;
import com.app.dc.service.simulation.runtime.SliceOptimizedWalkForwardRunner;
import com.app.dc.service.simulation.runtime.StrategyCandidateRow;
import com.app.dc.service.simulation.runtime.VersionedBacktestRunner;
import com.app.dc.service.simulation.scene.DeepSeekSceneTimelineService;

import java.lang.reflect.Field;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Properties;

/** Uses unchanged formal fit selection and execution. Validation-only mode cannot execute forward/full-period windows. */
public final class FitOnlyValidationReplayCli {
    static final Class<?> WINDOW;
    static {
        try { WINDOW = Class.forName(SliceOptimizedWalkForwardRunner.class.getName() + "$WindowSlice"); }
        catch (Exception error) { throw new ExceptionInInitializerError(error); }
    }

    static Method method(String name, Class<?>... types) throws Exception {
        Method method = SliceOptimizedWalkForwardRunner.class.getDeclaredMethod(name, types);
        method.setAccessible(true);
        return method;
    }

    static Object invoke(Method method, Object target, Object... args) throws Exception {
        try { return method.invoke(target, args); }
        catch (InvocationTargetException error) {
            Throwable cause = error.getCause();
            if (cause instanceof Exception) throw (Exception) cause;
            throw error;
        }
    }

    static Object field(Object target, String name) throws Exception {
        Field field = target.getClass().getDeclaredField(name);
        field.setAccessible(true);
        return field.get(target);
    }

    static final class WindowGuard extends VersionedBacktestRunner {
        final Map<String, String> allowed = new LinkedHashMap<String, String>();
        final Map<String, Integer> calls = new LinkedHashMap<String, Integer>();

        void allow(LocalDate begin, LocalDate end, String phase) {
            allowed.put(begin + "/" + end, phase);
        }

        void check(BacktestParam param, List<TTbookOhlc> rows) {
            String key = param.beginDate + "/" + param.endDate;
            OfflineTemporalReplayCli.require(allowed.containsKey(key), "validation-only execution forbids forward/full-period window " + key);
            OfflineTemporalReplayCli.require(rows != null && !rows.isEmpty(), "empty actual-engine window");
            for (TTbookOhlc row : rows) {
                String day = row.starttime.substring(0, 10);
                OfflineTemporalReplayCli.require(day.compareTo(param.beginDate) >= 0 && day.compareTo(param.endDate) <= 0,
                        "out-of-window price reached a fit/validate engine");
            }
            calls.put(key, calls.containsKey(key) ? calls.get(key) + 1 : 1);
        }

        @Override public BacktestModels.BacktestResult run(StrategyCandidateRow candidate, BacktestParam param,
                                                           List<TTbookOhlc> rows) throws Exception {
            check(param, rows);
            return super.run(candidate, param, rows);
        }

        @Override public BacktestModels.BacktestResult runSceneGated(StrategyCandidateRow candidate, BacktestParam param,
                List<TTbookOhlc> rows, DeepSeekSceneTimelineService.Cursor cursor,
                BacktestModels.SceneShadowMetrics metrics) throws Exception {
            check(param, rows);
            return super.runSceneGated(candidate, param, rows, cursor, metrics);
        }
    }

    static final class Harness {
        final OfflineTemporalReplayCli.Engine engine;
        final BacktestOptimizationService optimizer = new BacktestOptimizationService();
        final SliceOptimizedWalkForwardRunner walk = new SliceOptimizedWalkForwardRunner();
        final WindowGuard guard;

        Harness(Properties properties, boolean validationOnly) throws Exception {
            engine = new OfflineTemporalReplayCli.Engine(properties);
            guard = validationOnly ? new WindowGuard() : null;
            VersionedBacktestRunner runner = guard == null ? engine.runner : guard;
            if (guard != null) {
                OfflineTemporalReplayCli.configureValues(guard, VersionedBacktestRunner.class, properties, engine.effective);
                OfflineTemporalReplayCli.inject(guard, VersionedBacktestRunner.class, "legacyBacktestService", engine.legacy);
                OfflineTemporalReplayCli.inject(guard, VersionedBacktestRunner.class, "supportService", engine.support);
                OfflineTemporalReplayCli.inject(guard, VersionedBacktestRunner.class, "tradeService", engine.trades);
                OfflineTemporalReplayCli.inject(guard, VersionedBacktestRunner.class, "metricService", engine.metrics);
                OfflineTemporalReplayCli.inject(guard, VersionedBacktestRunner.class, "runtimeFacade", engine.facade);
            }
            OfflineTemporalReplayCli.inject(walk, SliceOptimizedWalkForwardRunner.class, "versionedBacktestRunner", runner);
            OfflineTemporalReplayCli.inject(walk, SliceOptimizedWalkForwardRunner.class, "supportService", engine.support);
            OfflineTemporalReplayCli.inject(walk, SliceOptimizedWalkForwardRunner.class, "backtestOptimizationService", optimizer);
            OfflineTemporalReplayCli.inject(walk, SliceOptimizedWalkForwardRunner.class, "executionStressService", engine.stress);
        }
    }

    static void verifyFourJointProfiles(Harness harness, BacktestOptimizationService.OptimizationPlan plan) {
        OfflineTemporalReplayCli.require(plan.optimizationSupported && "FEE_ADJUSTED_PROFIT_FIRST".equals(plan.objective),
                "actual four-profile fee-adjusted optimization is required");
        List<Map<String, Object>> values = harness.optimizer.buildCoarseParamSets(plan);
        OfflineTemporalReplayCli.require(values.size() == 4 && plan.dimensions.size() == 1, "profile grid changed");
        for (int i = 0; i < 4; i++) {
            Map<String, Object> value = values.get(i);
            OfflineTemporalReplayCli.require(value.size() == 1 && Integer.valueOf(i).equals(value.get("riskProfile")),
                    "must enumerate exactly one joint integer ordinal, in the frozen order");
        }
        OfflineTemporalReplayCli.require(harness.optimizer.buildFineParamSets(plan,
                new ArrayList<BacktestModels.OptimizationTrial>()).isEmpty(), "fine expansion is forbidden");
    }

    static final class ValidationResult {
        BacktestModels.BacktestResult aggregate;
        final List<Map<String, Object>> slices = new ArrayList<Map<String, Object>>();
        Map<String, Object> representative;
        Map<String, Integer> executionCalls;
    }

    @SuppressWarnings("unchecked")
    static ValidationResult validationOnly(Harness harness, OfflineTemporalReplayCli.Replay replay,
            BacktestOptimizationService.OptimizationPlan plan, int trialBudget) throws Exception {
        OfflineTemporalReplayCli.require(harness.guard != null, "window fence required");
        verifyFourJointProfiles(harness, plan);
        replay.param.strategyParams.clear();
        LocalDate first = LocalDate.parse(replay.param.beginDate), last = LocalDate.parse(replay.param.endDate);
        OfflineTemporalReplayCli.require(replay.bars.get(0).starttime.startsWith(first.toString())
                && replay.bars.get(replay.bars.size() - 1).starttime.startsWith(last.toString()), "market endpoints are incomplete");
        List<?> windows = (List<?>) invoke(method("buildSlices", LocalDate.class, LocalDate.class,
                int.class, int.class, int.class), harness.walk, first, last,
                plan.fitWindowDays, plan.validateWindowDays, plan.forwardWindowDays);
        OfflineTemporalReplayCli.require(windows.size() >= Math.max(3, plan.minSliceCount), "insufficient full primary folds");
        int budget = (Integer) invoke(method("resolvePerSliceBudget", int.class, int.class), harness.walk, trialBudget, windows.size());
        OfflineTemporalReplayCli.require(Math.max(1, budget / 2) >= 4, "existing trial budget truncates the frozen grid");
        ValidationResult output = new ValidationResult();
        output.aggregate = (BacktestModels.BacktestResult) invoke(method("initAggregate", StrategyCandidateRow.class, BacktestParam.class),
                harness.walk, replay.candidate, replay.param);
        List<Map<String, Object>> parameters = new ArrayList<Map<String, Object>>();
        BigDecimal fitPnl = BigDecimal.ZERO, validatePnl = BigDecimal.ZERO, adjustedValidate = BigDecimal.ZERO;
        int trial = 1, index = 0;
        Method filter = method("filterRows", List.class, LocalDate.class, LocalDate.class);
        Method select = method("selectBestParamForSlice", StrategyCandidateRow.class, BacktestParam.class,
                BacktestOptimizationService.OptimizationPlan.class, List.class, WINDOW,
                int.class, int.class, int.class, DeepSeekSceneTimelineService.Timeline.class);
        Method run = method("runWindow", StrategyCandidateRow.class, BacktestParam.class, Map.class, List.class,
                LocalDate.class, LocalDate.class, DeepSeekSceneTimelineService.Timeline.class);
        for (Object window : windows) {
            index++;
            LocalDate fitBegin = (LocalDate) field(window, "fitBegin"), fitEnd = (LocalDate) field(window, "fitEnd");
            LocalDate valBegin = (LocalDate) field(window, "validateBegin"), valEnd = (LocalDate) field(window, "validateEnd");
            harness.guard.allow(fitBegin, fitEnd, "FIT"); harness.guard.allow(valBegin, valEnd, "VALIDATE");
            List<TTbookOhlc> fitRows = (List<TTbookOhlc>) invoke(filter, harness.walk, replay.bars, fitBegin, fitEnd);
            List<TTbookOhlc> valRows = (List<TTbookOhlc>) invoke(filter, harness.walk, replay.bars, valBegin, valEnd);
            Object selection = invoke(select, harness.walk, replay.candidate, replay.param, plan, fitRows, window,
                    index, budget, trial, replay.timeline);
            trial = (Integer) field(selection, "nextTrialNo");
            Map<String, Object> chosen = new LinkedHashMap<String, Object>((Map<String, Object>) field(selection, "paramSet"));
            parameters.add(chosen);
            BacktestModels.BacktestResult fit = (BacktestModels.BacktestResult) field(selection, "fitResult");
            BacktestModels.BacktestResult validate = (BacktestModels.BacktestResult) invoke(run, harness.walk,
                    replay.candidate, replay.param, chosen, valRows, valBegin, valEnd, replay.timeline);
            invoke(method("mergeValidatePhase", BacktestModels.BacktestResult.class, BacktestModels.BacktestResult.class),
                    harness.walk, output.aggregate, validate);
            fitPnl = fitPnl.add(fit.totalPnl); validatePnl = validatePnl.add(validate.totalPnl);
            adjustedValidate = adjustedValidate.add(harness.engine.stress.adjustedPnl(validate));
            output.aggregate.maxDrawdownPct = output.aggregate.maxDrawdownPct.max(validate.maxDrawdownPct);
            Map<String, Object> row = new LinkedHashMap<String, Object>();
            row.put("sliceNo", index); row.put("fitBegin", fitBegin.toString()); row.put("fitEnd", fitEnd.toString());
            row.put("validateBegin", valBegin.toString()); row.put("validateEnd", valEnd.toString());
            row.put("forwardBegin", field(window, "forwardBegin").toString());
            row.put("forwardEnd", field(window, "forwardEnd").toString());
            row.put("bestParamSetJson", JSON.toJSONString(chosen));
            row.put("fitScore", ((BigDecimal) field(selection, "fitScore")).setScale(6, RoundingMode.HALF_UP));
            row.put("fitPnl", fit.totalPnl); row.put("validatePnl", validate.totalPnl);
            row.put("validateTradeCount", validate.tradeCount); row.put("validateTrades", validate.tradeList);
            row.put("feeAdjustedValidatePnl", harness.engine.stress.adjustedPnl(validate));
            row.put("forwardMetrics", "WITHHELD"); output.slices.add(row);
            OfflineTemporalReplayCli.require(Integer.valueOf(4).equals(harness.guard.calls.get(fitBegin + "/" + fitEnd))
                    && Integer.valueOf(1).equals(harness.guard.calls.get(valBegin + "/" + valEnd)), "unexpected fit or validation execution count");
        }
        output.aggregate.fitPnl = fitPnl.setScale(6, RoundingMode.HALF_UP);
        output.aggregate.validatePnl = validatePnl.setScale(6, RoundingMode.HALF_UP);
        output.aggregate.totalPnl = output.aggregate.validatePnl;
        output.aggregate.feeAdjustedValidatePnl = adjustedValidate.setScale(6, RoundingMode.HALF_UP);
        output.aggregate.profitFactor = (BigDecimal) invoke(method("calcProfitFactor", List.class), harness.walk, output.aggregate.tradeList);
        output.representative = (Map<String, Object>) invoke(method("buildRepresentativeParamSet", List.class), harness.walk, parameters);
        output.executionCalls = new LinkedHashMap<String, Integer>(harness.guard.calls);
        return output;
    }

    static BacktestModels.BacktestResult fullPrimary(Harness harness, OfflineTemporalReplayCli.Replay replay,
            BacktestOptimizationService.OptimizationPlan plan, int budget) throws Exception {
        OfflineTemporalReplayCli.require(harness.guard == null, "formal primary cannot use a validation-only harness");
        verifyFourJointProfiles(harness, plan);
        replay.param.strategyParams.clear();
        return harness.walk.runSceneConditioned(replay.candidate, replay.param, replay.bars, plan,
                plan.fitWindowDays, plan.validateWindowDays, plan.forwardWindowDays, Math.max(3, plan.minSliceCount), budget, replay.timeline);
    }

    @SuppressWarnings("unchecked")
    static Map<String, Object> firstFitOnly(Harness harness, OfflineTemporalReplayCli.Replay replay,
            BacktestOptimizationService.OptimizationPlan plan, int trialBudget) throws Exception {
        OfflineTemporalReplayCli.require(harness.guard != null, "fit fence required");
        verifyFourJointProfiles(harness, plan);
        replay.param.strategyParams.clear();
        List<?> windows = (List<?>) invoke(method("buildSlices", LocalDate.class, LocalDate.class,
                int.class, int.class, int.class), harness.walk, LocalDate.parse(replay.param.beginDate),
                LocalDate.parse(replay.param.endDate), plan.fitWindowDays, plan.validateWindowDays, plan.forwardWindowDays);
        OfflineTemporalReplayCli.require(!windows.isEmpty(), "first-fit window missing");
        Object window = windows.get(0);
        LocalDate first = (LocalDate) field(window, "fitBegin"), last = (LocalDate) field(window, "fitEnd");
        harness.guard.allow(first, last, "FIT");
        List<TTbookOhlc> rows = (List<TTbookOhlc>) invoke(method("filterRows", List.class, LocalDate.class, LocalDate.class),
                harness.walk, replay.bars, first, last);
        int budget = (Integer) invoke(method("resolvePerSliceBudget", int.class, int.class), harness.walk, trialBudget, windows.size());
        Object selection = invoke(method("selectBestParamForSlice", StrategyCandidateRow.class, BacktestParam.class,
                BacktestOptimizationService.OptimizationPlan.class, List.class, WINDOW,
                int.class, int.class, int.class, DeepSeekSceneTimelineService.Timeline.class),
                harness.walk, replay.candidate, replay.param, plan, rows, window, 1, budget, 1, replay.timeline);
        Map<String, Object> result = new LinkedHashMap<String, Object>();
        result.put("selected", field(selection, "paramSet")); result.put("score", field(selection, "fitScore"));
        result.put("fitPnl", ((BacktestModels.BacktestResult) field(selection, "fitResult")).totalPnl);
        result.put("trials", field(selection, "optimizationTrials"));
        OfflineTemporalReplayCli.require(harness.guard.calls.size() == 1
                && Integer.valueOf(4).equals(harness.guard.calls.get(first + "/" + last)), "first fit accessed a non-fit window");
        return result;
    }

    public static void main(String[] args) throws Exception {
        OfflineTemporalReplayCli.require(args.length == 3, "expected frozen validation spec, execution properties, output");
        OfflineTemporalReplayCli.require(ZoneOffset.UTC.equals(ZoneId.systemDefault().getRules().getOffset(Instant.now())), "UTC required");
        JSONObject spec = JSON.parseObject(new String(Files.readAllBytes(Paths.get(args[0])), StandardCharsets.UTF_8));
        OfflineTemporalReplayCli.require("validation_only".equals(spec.getString("researchMode")), "only explicit validation mode is exposed here");
        JSONObject protocol = JSON.parseObject(new String(OfflineTemporalReplayCli.verified(Paths.get(spec.getString("protocolPath")),
                spec.getString("protocolSha256")), StandardCharsets.UTF_8));
        OfflineTemporalReplayCli.require("temporal_source_research_v2".equals(protocol.getString("protocol_version"))
                && protocol.getString("primary_begin").equals(spec.getString("beginDate"))
                && protocol.getString("primary_end_inclusive").equals(spec.getString("endDate")), "frozen primary protocol mismatch");
        Properties properties = new Properties();
        try (java.io.InputStream stream = Files.newInputStream(Paths.get(args[1]))) { properties.load(stream); }
        OfflineTemporalReplayCli.Replay replay = new OfflineTemporalReplayCli.Replay(spec);
        Harness harness = new Harness(properties, true);
        try {
            BacktestOptimizationService.OptimizationPlan plan = harness.optimizer.buildPlan(replay.candidate.parametersJson);
            ValidationResult result = validationOnly(harness, replay, plan, Integer.parseInt(properties.getProperty("strategy.backtest.maxTrialsPerTask", "1000")));
            Map<String, Object> output = new LinkedHashMap<String, Object>();
            output.put("schema", "actual_fit_validation_only_v1"); output.put("sliceResults", result.slices);
            output.put("tradeCount", result.aggregate.tradeCount); output.put("profitFactor", result.aggregate.profitFactor);
            output.put("maxDrawdownPct", result.aggregate.maxDrawdownPct);
            output.put("feeAdjustedValidatePnl", result.aggregate.feeAdjustedValidatePnl);
            output.put("selectedParameters", result.representative); output.put("executionCalls", result.executionCalls);
            output.put("forwardMetrics", "WITHHELD"); output.put("fullPeriodSafety", "WITHHELD");
            output.put("qualified", false); output.put("productionWrite", false);
            Files.write(Paths.get(args[2]), (JSON.toJSONString(output) + "\n").getBytes(StandardCharsets.UTF_8));
        } finally {
            harness.engine.facade.unload(replay.candidate.strategyName, replay.candidate.strategyVersion);
        }
    }
}
