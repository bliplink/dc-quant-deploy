package com.app.dc.service.cluster;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import com.alibaba.fastjson2.JSON;
import com.alibaba.fastjson2.JSONObject;

/** Standalone regressions run against the exact freshly built Trade runtime classes. */
public final class TradeEmptyGenesisBootstrapTest {
    interface Action { void run() throws Exception; }
    static int passed;
    static void rejects(Action action) throws Exception {
        try { action.run(); throw new AssertionError("unsafe genesis accepted"); }
        catch (IllegalStateException expected) { passed++; }
    }
    static Path proof(Path root, String id) throws Exception {
        JSONObject value = new JSONObject(); value.put("runtimeRoot", root.toString()); value.put("resetId", id);
        value.put("dataResetCompleted", true); value.put("completedAtMillis", System.currentTimeMillis());
        value.put("deletedComponents", Arrays.asList("TradeSvrA", "TradeSvrB", "zookeeper"));
        Path path = root.resolve("reset.json"); Files.write(path, JSON.toJSONBytes(value)); return path;
    }
    static Path catalog(Path root) throws Exception {
        StringBuilder rows = new StringBuilder();
        for (int index = 0; index < 256; index++) {
            String primary = index % 2 == 0 ? "TradeSvrA" : "TradeSvrB";
            String replica = index % 2 == 0 ? "TradeSvrB" : "TradeSvrA";
            JSONObject row = new JSONObject(); row.put("partitionId", String.format("P%03d", index));
            row.put("epoch", 1); row.put("assignmentVersion", 1); row.put("protocolVersion", 3);
            row.put("primary", primary); row.put("replica", replica); row.put("replicas", Arrays.asList(replica));
            row.put("learners", Arrays.asList()); row.put("state", "READY"); rows.append(row).append('\n');
        }
        Path path = root.resolve("assignments.jsonl"); Files.write(path, rows.toString().getBytes(StandardCharsets.UTF_8)); return path;
    }
    public static void main(String[] args) throws Exception {
        Path root = Files.createTempDirectory("genesis-acceptance-"); Path proof = proof(root, "reset-fixture0001");
        Path assignments = catalog(root);
        Path data = root.resolve("data/TradeSvrB"); Files.createDirectories(data); Files.write(data.resolve("old-journal"), new byte[] {1});
        rejects(() -> TradeEmptyGenesisBootstrap.bootstrap(root, proof, assignments));
        if (Files.exists(proof.resolveSibling("reset.json.genesis-started"))) throw new AssertionError("proof consumed on preflight refusal");
        Files.delete(data.resolve("old-journal"));
        JSONObject stale = JSON.parseObject(new String(Files.readAllBytes(proof), StandardCharsets.UTF_8));
        stale.put("completedAtMillis", 1); Files.write(proof, JSON.toJSONBytes(stale));
        rejects(() -> TradeEmptyGenesisBootstrap.bootstrap(root, proof, assignments)); proof(root, "reset-fixture0001");
        Path linked = root.resolve("data/TradeSvrA"); Files.createSymbolicLink(linked, data);
        rejects(() -> TradeEmptyGenesisBootstrap.bootstrap(root, proof, assignments)); Files.delete(linked);
        String rows = new String(Files.readAllBytes(assignments), StandardCharsets.UTF_8);
        Files.write(assignments, rows.replace("\"epoch\":1", "\"epoch\":2").getBytes(StandardCharsets.UTF_8));
        rejects(() -> TradeEmptyGenesisBootstrap.bootstrap(root, proof, assignments)); catalog(root);
        TradeEmptyGenesisBootstrap.bootstrap(root, proof, assignments); passed++;
        rejects(() -> TradeEmptyGenesisBootstrap.bootstrap(root, proof, assignments));
        // Lost directory cannot be promoted with the same already-consumed reset evidence.
        Path reuse = Files.createTempDirectory("genesis-reuse-refused-"); Path reuseProof = proof(reuse, "reset-fixture0002");
        Path reuseCatalog = catalog(reuse); Files.write(reuseProof.resolveSibling("reset.json.genesis-started"), new byte[] {1});
        rejects(() -> TradeEmptyGenesisBootstrap.bootstrap(reuse, reuseProof, reuseCatalog));
        System.out.println("GENESIS_TEST_PASS cases=" + passed);
    }
}
