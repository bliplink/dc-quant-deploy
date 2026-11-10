package com.app.dc.service.simulation;

import com.alibaba.fastjson2.JSON;
import com.alibaba.fastjson2.JSONObject;
import com.app.dc.po.backtest.BacktestParam;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Properties;

/** Training-only comparison against complete unchanged v4, including four-profile fit choices and exact trade fields. */
public final class FitOnlyValidationReplayOracleCli {
    static void same(Object expected, Object actual, String label) {
        OfflineTemporalReplayCli.require(JSON.toJSONString(expected).equals(JSON.toJSONString(actual)),
                "fit/validation oracle mismatch: " + label);
    }

    public static void main(String[] args) throws Exception {
        OfflineTemporalReplayCli.require(args.length == 3, "expected training oracle spec, config, output");
        JSONObject spec = JSON.parseObject(new String(Files.readAllBytes(Paths.get(args[0])), StandardCharsets.UTF_8));
        OfflineTemporalReplayCli.require(spec.getBooleanValue("trainingOnly")
                && !spec.getBooleanValue("formalHoldout") && spec.getString("endDate").compareTo("2024-12-15") < 0,
                "oracle can only execute pre-validation training history");
        Properties properties = new Properties();
        try (java.io.InputStream stream = Files.newInputStream(Paths.get(args[1]))) { properties.load(stream); }
        int trialBudget = Integer.parseInt(properties.getProperty("strategy.backtest.maxTrialsPerTask", "1000"));
        OfflineTemporalReplayCli.Replay validationReplay = new OfflineTemporalReplayCli.Replay(spec);
        OfflineTemporalReplayCli.Replay referenceReplay = new OfflineTemporalReplayCli.Replay(spec);
        FitOnlyValidationReplayCli.Harness validation = new FitOnlyValidationReplayCli.Harness(properties, true);
        FitOnlyValidationReplayCli.Harness reference = new FitOnlyValidationReplayCli.Harness(properties, false);
        FitOnlyValidationReplayCli.Harness firstFit = new FitOnlyValidationReplayCli.Harness(properties, true);
        FitOnlyValidationReplayCli.Harness perturbedFit = new FitOnlyValidationReplayCli.Harness(properties, true);
        try {
            BacktestOptimizationService.OptimizationPlan plan = validation.optimizer.buildPlan(validationReplay.candidate.parametersJson);
            FitOnlyValidationReplayCli.ValidationResult a = FitOnlyValidationReplayCli.validationOnly(validation, validationReplay, plan, trialBudget);
            BacktestModels.BacktestResult b = FitOnlyValidationReplayCli.fullPrimary(reference, referenceReplay,
                    reference.optimizer.buildPlan(referenceReplay.candidate.parametersJson), trialBudget);
            same(b.fitPnl, a.aggregate.fitPnl, "aggregate fit");
            same(b.validatePnl, a.aggregate.validatePnl, "aggregate validate");
            same(b.feeAdjustedValidatePnl, a.aggregate.feeAdjustedValidatePnl, "fee-adjusted validate");
            same(b.profitFactor, a.aggregate.profitFactor, "profit factor");
            same(b.maxDrawdownPct, a.aggregate.maxDrawdownPct, "drawdown");
            same(b.tradeCount, a.aggregate.tradeCount, "trade count");
            same(b.tradeList, a.aggregate.tradeList, "every validation trade, fee, capital and exit field");
            same(b.rejectReasonCounts, a.aggregate.rejectReasonCounts, "economics and scene rejections");
            same(JSON.parseObject(b.bestParamSetJson), new JSONObject(a.representative), "actual representative parameter rule");
            OfflineTemporalReplayCli.require(a.slices.size() == b.sliceResults.size() && b.tradeCount > 0,
                    "oracle requires nonzero actual trades and all primary folds");
            for (int i = 0; i < a.slices.size(); i++) {
                Map<String, Object> actual = a.slices.get(i);
                BacktestModels.BacktestSliceResult expected = b.sliceResults.get(i);
                same(expected.bestParamSetJson, actual.get("bestParamSetJson"), "fold parameter choice");
                same(expected.fitScore, actual.get("fitScore"), "fold fee-adjusted fit score");
                same(expected.fitPnl, actual.get("fitPnl"), "fold fit PnL");
                same(expected.validatePnl, actual.get("validatePnl"), "fold validation PnL");
                same(expected.validateTradeCount, actual.get("validateTradeCount"), "fold validation sample count");
                same(expected.fitBegin, actual.get("fitBegin"), "fold fit begin");
                same(expected.forwardEnd, actual.get("forwardEnd"), "fold policy dates");
            }
            BacktestParam forbidden = new BacktestParam();
            forbidden.beginDate = a.slices.get(0).get("forwardBegin").toString();
            forbidden.endDate = a.slices.get(0).get("forwardEnd").toString();
            boolean rejected = false;
            try {
                validation.guard.runSceneGated(validationReplay.candidate, forbidden, validationReplay.bars,
                        validationReplay.timeline.cursor(), new BacktestModels.SceneShadowMetrics());
            } catch (IllegalArgumentException expected) {
                rejected = expected.getMessage().contains("forbids forward/full-period");
            }
            OfflineTemporalReplayCli.require(rejected, "forward execution fence did not reject");
            JSONObject changed = JSON.parseObject(spec.toJSONString());
            changed.put("barsPath", spec.getString("perturbedBarsPath"));
            changed.put("barsSha256", spec.getString("perturbedBarsSha256"));
            OfflineTemporalReplayCli.Replay unchangedFitData = new OfflineTemporalReplayCli.Replay(spec);
            OfflineTemporalReplayCli.Replay futureChanged = new OfflineTemporalReplayCli.Replay(changed);
            Map<String, Object> originalChoice = FitOnlyValidationReplayCli.firstFitOnly(firstFit, unchangedFitData,
                    firstFit.optimizer.buildPlan(unchangedFitData.candidate.parametersJson), trialBudget);
            Map<String, Object> changedChoice = FitOnlyValidationReplayCli.firstFitOnly(perturbedFit, futureChanged,
                    perturbedFit.optimizer.buildPlan(futureChanged.candidate.parametersJson), trialBudget);
            same(originalChoice, changedChoice, "future OHLCV perturbation must not change first-fit trial metrics or selection");
            Map<String, Object> output = new LinkedHashMap<String, Object>();
            output.put("passed", true); output.put("folds", a.slices.size()); output.put("trades", b.tradeCount);
            output.put("selectedParameters", a.representative); output.put("guardCalls", a.executionCalls);
            output.put("primaryEngine", "unchanged_SliceOptimizedWalkForwardRunner");
            output.put("exactValidationTradesAndFitChoices", true); output.put("forwardFenceRejected", true);
            output.put("firstFitFuturePerturbationInvariant", true); output.put("trainingOnly", true);
            output.put("trainingReferenceForwardComputed", true); output.put("newHoldoutRead", false);
            output.put("productionWrite", false);
            Files.write(Paths.get(args[2]), (JSON.toJSONString(output) + "\n").getBytes(StandardCharsets.UTF_8));
            System.out.println("FIT_ONLY_VALIDATION_ORACLE_PASSED folds=" + a.slices.size() + " trades=" + b.tradeCount);
        } finally {
            String name = validationReplay.candidate.strategyName, version = validationReplay.candidate.strategyVersion;
            validation.engine.facade.unload(name, version); reference.engine.facade.unload(name, version);
            firstFit.engine.facade.unload(name, version); perturbedFit.engine.facade.unload(name, version);
        }
    }
}
