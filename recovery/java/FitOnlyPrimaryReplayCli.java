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

/** Offline complete unchanged v4 primary; holdout is a separate, explicitly locked invocation. */
public final class FitOnlyPrimaryReplayCli {
    public static void main(String[] args) throws Exception {
        OfflineTemporalReplayCli.require(args.length == 3, "expected frozen primary specification, properties, output");
        OfflineTemporalReplayCli.require(ZoneOffset.UTC.equals(ZoneId.systemDefault().getRules().getOffset(Instant.now())), "UTC required");
        OfflineTemporalReplayCli.require(!Files.exists(Paths.get(args[2])), "preserve every consumed primary result");
        JSONObject spec = JSON.parseObject(new String(Files.readAllBytes(Paths.get(args[0])), StandardCharsets.UTF_8));
        OfflineTemporalReplayCli.require("full_primary".equals(spec.getString("researchMode"))
                && !spec.getBooleanValue("formalHoldout"), "explicit primary-only replay required");
        JSONObject protocol = JSON.parseObject(new String(OfflineTemporalReplayCli.verified(Paths.get(spec.getString("protocolPath")),
                spec.getString("protocolSha256")), StandardCharsets.UTF_8));
        OfflineTemporalReplayCli.require("temporal_source_research_v2".equals(protocol.getString("protocol_version"))
                && protocol.getString("primary_begin").equals(spec.getString("beginDate"))
                && protocol.getString("primary_end_inclusive").equals(spec.getString("endDate")), "primary protocol changed");
        Properties properties = new Properties();
        try (java.io.InputStream stream = Files.newInputStream(Paths.get(args[1]))) { properties.load(stream); }
        OfflineTemporalReplayCli.Replay replay = new OfflineTemporalReplayCli.Replay(spec);
        FitOnlyValidationReplayCli.Harness harness = new FitOnlyValidationReplayCli.Harness(properties, false);
        try {
            BacktestModels.BacktestResult result = FitOnlyValidationReplayCli.fullPrimary(harness, replay,
                    harness.optimizer.buildPlan(replay.candidate.parametersJson),
                    Integer.parseInt(properties.getProperty("strategy.backtest.maxTrialsPerTask", "1000")));
            // Call the existing qualification gate, rather than maintaining a new approximation.
            Method gate = LocalBacktestCli.class.getDeclaredMethod("qualificationReason", BacktestModels.BacktestResult.class);
            gate.setAccessible(true);
            String reason = (String) gate.invoke(null, result);
            Map<String, Object> output = new LinkedHashMap<String, Object>();
            output.put("result", result); output.put("primaryQualified", "qualified".equals(reason));
            output.put("qualificationReason", reason); output.put("selectedParameters", JSON.parseObject(result.bestParamSetJson));
            output.put("beginDate", replay.param.beginDate); output.put("endDate", replay.param.endDate);
            output.put("sourceSha256", replay.sourceSha); output.put("artifactSha256", spec.getString("artifactSha256"));
            output.put("newHoldoutRead", false); output.put("productionWrite", false);
            output.put("effectiveExecutionConfig", harness.engine.effective);
            Files.write(Paths.get(args[2]), (JSON.toJSONString(output) + "\n").getBytes(StandardCharsets.UTF_8));
            System.out.println("OFFLINE_FIT_PRIMARY_COMPLETE qualified=" + "qualified".equals(reason));
        } finally {
            harness.engine.facade.unload(replay.candidate.strategyName, replay.candidate.strategyVersion);
        }
    }
}
