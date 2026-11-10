package com.app.dc.service.simulation;

import com.app.dc.service.simulation.runtime.StrategyAutoPublishService;
import com.app.dc.service.simulation.runtime.StrategyBacktestSummary;
import com.app.dc.service.simulation.runtime.StrategyCandidateRow;
import com.gateway.connector.utils.JsonUtils;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Observation-only synthetic-summary probe. Never calls publish/DAO, replay or registry methods. */
public class FixedPolicyPublicationGateProbe {
    static void set(Object target, String name, Object value) throws Exception {
        Field field = target.getClass().getDeclaredField(name); field.setAccessible(true); field.set(target, value);
    }
    static Object get(Object target, String name) throws Exception {
        Field field = target.getClass().getDeclaredField(name); field.setAccessible(true); return field.get(target);
    }
    static String gate(StrategyAutoPublishService service, StrategyBacktestSummary summary) throws Exception {
        Method method = service.getClass().getDeclaredMethod("validatePublishThresholds", StrategyBacktestSummary.class);
        method.setAccessible(true); return (String) method.invoke(service, summary);
    }
    static StrategyBacktestSummary passingSummary() {
        StrategyBacktestSummary s = new StrategyBacktestSummary();
        s.executionModelVersion = BacktestModels.EXECUTION_MODEL_VERSION;
        s.windowMode = BacktestModels.SCENE_CONDITIONED_WINDOW_MODE;
        s.fullPeriodSafetyPass = true; s.trialCount = 0; s.sliceCount = 5;
        s.sceneQualificationPass = true; s.sceneRecordCount = 730; s.sceneMatchedBarCount = 10000;
        s.sceneTradeCount = 40; s.scenePnl = 200D; s.sceneProfitFactor = 1.5; s.sceneMaxDrawdownPct = .05;
        s.overfitPass = 1; s.oosPass = 1; s.validatePrimaryScore = 200D; s.validatePnl = 200D;
        s.validateTradeCount = 40; s.validateMaxDrawdownPct = .05; s.validateProfitFactor = 1.5;
        s.feeAdjustedValidatePnl = 150D; s.feeAdjustedForwardPnl = 60D; s.forwardPnl = 70D;
        s.forwardScore = .02; s.totalPnl = 200D; s.minForwardContribution = .20; s.fragileBest = 0;
        s.bestParamSetJson = "{}"; return s;
    }
    public static void main(String[] args) throws Exception {
        StrategyAutoPublishService service = new StrategyAutoPublishService();
        set(service, "sceneQualificationEnabled", true); set(service, "sceneMinRecords", 30);
        set(service, "sceneMinTrades", 5); set(service, "sceneMinProfitFactor", 1.05);
        set(service, "sceneMaxDrawdownPct", .25); set(service, "minValidateTrades", 20);
        set(service, "maxValidateDrawdownPct", .15); set(service, "minValidateProfitFactor", 1.20);
        String parameters = "{\"parameterSchema\":{},\"defaultParams\":{},\"optimizationProfile\":{\"minForwardContribution\":0.20}}";
        BacktestOptimizationService optimizer = new BacktestOptimizationService();
        BacktestOptimizationService.OptimizationPlan plan = optimizer.buildPlan(parameters);
        List<Map<String, Object>> defaults = optimizer.buildDefaultOnly(plan);
        StrategyCandidateRow candidate = new StrategyCandidateRow(); candidate.parametersJson = parameters;
        Method expects = service.getClass().getDeclaredMethod("expectsOptimizationEvidence", StrategyCandidateRow.class);
        expects.setAccessible(true);
        Method global = service.getClass().getDeclaredMethod("validateGlobalPreconditions", StrategyBacktestSummary.class, StrategyCandidateRow.class);
        global.setAccessible(true);
        Map<String, Object> result = new LinkedHashMap<String, Object>();
        result.put("schema", "fixed_policy_publication_gate_observation_v1");
        result.put("synthetic_summary_only", true); result.put("financial_replay_performed", false);
        result.put("production_write", false); result.put("publish_or_dao_invocations", 0);
        result.put("optimization_supported", get(plan, "optimizationSupported"));
        result.put("default_param_sets", defaults);
        result.put("expects_optimization_evidence", expects.invoke(service, candidate));
        result.put("global_precondition_reason", global.invoke(service, passingSummary(), candidate));
        result.put("fixed_empty_parameter_reason", gate(service, passingSummary()));
        StrategyBacktestSummary control = passingSummary(); control.bestParamSetJson = "{\"riskProfile\":1}";
        result.put("nonempty_parameter_control_only_reason", gate(service, control));
        result.put("control_is_not_a_proposed_dummy_parameter_workaround", true);
        StrategyBacktestSummary negative = passingSummary(); negative.feeAdjustedForwardPnl = -1D;
        result.put("negative_forward_reason", gate(service, negative));
        StrategyBacktestSummary oos = passingSummary(); oos.oosPass = 0;
        result.put("failed_oos_reason", gate(service, oos));
        StrategyBacktestSummary low = passingSummary(); low.feeAdjustedForwardPnl = 20D;
        result.put("low_contribution_reason", gate(service, low));
        StrategyBacktestSummary scene = passingSummary(); scene.sceneQualificationPass = false; scene.sceneQualificationReason = "scene fixture rejected";
        result.put("failed_scene_reason", gate(service, scene));
        if (!Boolean.FALSE.equals(result.get("optimization_supported")) || defaults.size() != 1 || !defaults.get(0).isEmpty()
                || !Boolean.FALSE.equals(result.get("expects_optimization_evidence"))
                || !"".equals(result.get("global_precondition_reason"))
                || !"best param set missing".equals(result.get("fixed_empty_parameter_reason"))
                || !"".equals(result.get("nonempty_parameter_control_only_reason"))
                || !"fee adjusted forward pnl <= 0".equals(result.get("negative_forward_reason"))
                || !"oos gate not passed".equals(result.get("failed_oos_reason"))
                || !"forward contribution below threshold".equals(result.get("low_contribution_reason"))
                || !"scene fixture rejected".equals(result.get("failed_scene_reason")))
            throw new IllegalStateException("actual unchanged publication probe differs from the observed contract");
        System.out.println("FIXED_POLICY_GATE_OBSERVATION=" + JsonUtils.Serializer(result));
    }
}
