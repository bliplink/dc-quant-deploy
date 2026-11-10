package com.app.dc.service.simulation;

import com.alibaba.fastjson2.JSON;
import com.alibaba.fastjson2.JSONObject;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Properties;

/** Offline fixed-source entry to the unchanged actual v4 walk-forward and existing financial gate. */
public final class FixedSourcePrimaryReplayCli {
    public static void main(String[] args) throws Exception {
        OfflineTemporalReplayCli.require(args.length == 3, "expected fixed primary spec, properties, output");
        OfflineTemporalReplayCli.require(ZoneOffset.UTC.equals(ZoneId.systemDefault().getRules().getOffset(Instant.now())), "UTC required");
        OfflineTemporalReplayCli.require(!Files.exists(Paths.get(args[2])), "preserve every consumed primary result");
        JSONObject spec = JSON.parseObject(new String(Files.readAllBytes(Paths.get(args[0])), StandardCharsets.UTF_8));
        OfflineTemporalReplayCli.require("fixed_full_primary".equals(spec.getString("researchMode"))
                && !spec.getBooleanValue("formalHoldout"), "fixed primary mode required");
        JSONObject protocol = JSON.parseObject(new String(OfflineTemporalReplayCli.verified(Paths.get(spec.getString("protocolPath")),
                spec.getString("protocolSha256")), StandardCharsets.UTF_8));
        OfflineTemporalReplayCli.require("temporal_source_research_v2".equals(protocol.getString("protocol_version"))
                && "fixed_source_no_parameter_grid".equals(protocol.getString("selection_mode"))
                && protocol.getString("primary_begin").equals(spec.getString("beginDate"))
                && protocol.getString("primary_end_inclusive").equals(spec.getString("endDate")), "fixed primary protocol mismatch");
        Properties properties = new Properties();
        try (java.io.InputStream stream = Files.newInputStream(Paths.get(args[1]))) { properties.load(stream); }
        OfflineTemporalReplayCli.Replay replay = new OfflineTemporalReplayCli.Replay(spec);
        FitOnlyValidationReplayCli.Harness harness = new FitOnlyValidationReplayCli.Harness(properties, false);
        try {
            BacktestOptimizationService.OptimizationPlan plan = harness.optimizer.buildPlan(replay.candidate.parametersJson);
            OfflineTemporalReplayCli.require(!plan.optimizationSupported && plan.dimensions.isEmpty()
                    && replay.locked.isEmpty() && harness.optimizer.buildDefaultOnly(plan).size() == 1
                    && harness.optimizer.buildDefaultOnly(plan).get(0).isEmpty(), "fixed-source replay forbids a parameter grid");
            BacktestModels.BacktestResult result = harness.walk.runSceneConditioned(replay.candidate, replay.param,
                    replay.bars, plan, plan.fitWindowDays, plan.validateWindowDays, plan.forwardWindowDays,
                    Math.max(3, plan.minSliceCount), Integer.parseInt(properties.getProperty("strategy.backtest.maxTrialsPerTask", "1000")), replay.timeline);
            Map<String, Object> checkpoint = new LinkedHashMap<String, Object>();
            checkpoint.put("result", result); checkpoint.put("sourceSha256", replay.sourceSha);
            checkpoint.put("artifactSha256", spec.getString("artifactSha256")); checkpoint.put("productionWrite", false);
            Files.write(Paths.get(args[2] + ".engine.json"), (JSON.toJSONString(checkpoint) + "\n").getBytes(StandardCharsets.UTF_8));
            OfflineTemporalReplayCli.require(JSON.parseObject(result.bestParamSetJson).isEmpty(), "fixed representative must be empty");
            Method gate = LocalBacktestCli.class.getDeclaredMethod("qualificationReason", BacktestModels.BacktestResult.class);
            gate.setAccessible(true);
            String reason = (String) gate.invoke(null, result);
            Map<String, Object> output = new LinkedHashMap<String, Object>();
            output.put("result", result); output.put("primaryQualified", "qualified".equals(reason));
            output.put("qualificationReason", reason); output.put("selectedParameters", new LinkedHashMap<String, Object>());
            output.put("beginDate", replay.param.beginDate); output.put("endDate", replay.param.endDate);
            output.put("sourceSha256", replay.sourceSha); output.put("artifactSha256", spec.getString("artifactSha256"));
            output.put("parameterGridSearch", false); output.put("newHoldoutRead", false); output.put("productionWrite", false);
            output.put("effectiveExecutionConfig", harness.engine.effective);
            Files.write(Paths.get(args[2]), (JSON.toJSONString(output) + "\n").getBytes(StandardCharsets.UTF_8));
            System.out.println("OFFLINE_FIXED_PRIMARY_COMPLETE qualified=" + "qualified".equals(reason));
        } finally {
            harness.engine.facade.unload(replay.candidate.strategyName, replay.candidate.strategyVersion);
        }
    }
}
