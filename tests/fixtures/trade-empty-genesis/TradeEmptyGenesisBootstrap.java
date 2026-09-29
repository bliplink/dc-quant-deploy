package com.app.dc.service.cluster;

import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import com.alibaba.fastjson2.JSON;
import com.alibaba.fastjson2.JSONObject;

/** Offline, operator-authorized fresh-test genesis; never a runtime fallback. */
public final class TradeEmptyGenesisBootstrap {
    private static void require(boolean value, String reason) {
        if (!value) throw new IllegalStateException("GENESIS_REFUSED: " + reason);
    }

    static void emptyDirectory(Path path) throws Exception {
        Path current = path.toAbsolutePath().normalize();
        for (Path part = current; part != null; part = part.getParent()) {
            require(!Files.isSymbolicLink(part), "symbolic link: " + part);
        }
        if (Files.exists(current)) {
            require(Files.isDirectory(current), "not a directory: " + current);
            try (java.util.stream.Stream<Path> children = Files.list(current)) {
                require(!children.findAny().isPresent(), "nonempty data: " + current);
            }
        }
    }

    static String sha256(Path path) throws Exception {
        byte[] hash = MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(path));
        StringBuilder result = new StringBuilder();
        for (byte value : hash) result.append(String.format("%02x", value & 255));
        return result.toString();
    }

    static List<String> validateAssignments(Path assignmentFile) throws Exception {
        List<String> lines = Files.readAllLines(assignmentFile, StandardCharsets.UTF_8);
        require(lines.size() == 256, "expected 256 actual assignments");
        Set<String> ids = new HashSet<String>();
        for (String line : lines) {
            JSONObject row = JSON.parseObject(line);
            String id = row.getString("partitionId");
            require(id != null && id.matches("P[0-9]{3}") && ids.add(id), "invalid/duplicate partition");
            int index = Integer.parseInt(id.substring(1));
            String primary = index % 2 == 0 ? "TradeSvrA" : "TradeSvrB";
            String replica = index % 2 == 0 ? "TradeSvrB" : "TradeSvrA";
            require(index < 256 && row.getLongValue("epoch") == 1L
                    && row.getLongValue("assignmentVersion") == 1L && row.getIntValue("protocolVersion") == 3
                    && "READY".equals(row.getString("state")) && primary.equals(row.getString("primary"))
                    && replica.equals(row.getString("replica"))
                    && row.getJSONArray("replicas") != null && row.getJSONArray("replicas").size() == 1
                    && replica.equals(row.getJSONArray("replicas").getString(0))
                    && row.getJSONArray("learners") != null && row.getJSONArray("learners").isEmpty(),
                    "assignment is not untouched fresh A/B catalog: " + id);
        }
        return lines;
    }

    static void bootstrap(Path root, Path resetFile, Path assignmentFile) throws Exception {
        root = root.toAbsolutePath().normalize();
        JSONObject reset = JSON.parseObject(new String(Files.readAllBytes(resetFile), StandardCharsets.UTF_8));
        String resetId = reset.getString("resetId");
        require(reset.getBooleanValue("dataResetCompleted") && root.toString().equals(reset.getString("runtimeRoot")),
                "missing successful reset proof");
        require(resetId != null && resetId.matches("reset-[a-zA-Z0-9-]{8,80}"), "invalid reset ID");
        require(reset.getJSONArray("confirmedAbsentComponents") != null
                && reset.getJSONArray("confirmedAbsentComponents").contains("TradeSvrA")
                && reset.getJSONArray("confirmedAbsentComponents").contains("TradeSvrB")
                && reset.getJSONArray("confirmedAbsentComponents").contains("zookeeper"), "incomplete reset scope proof");
        long age = System.currentTimeMillis() - reset.getLongValue("completedAtMillis");
        require(age >= 0 && age <= 3600000L, "reset proof expired");
        validateAssignments(assignmentFile);
        for (String node : new String[] {"TradeSvrA", "TradeSvrB"}) {
            emptyDirectory(root.resolve("data/" + node));
        }
        Path consumed = resetFile.resolveSibling(resetFile.getFileName() + ".genesis-started");
        require(!Files.exists(consumed), "reset proof already consumed; partial failures require a new reset");
        // Consume BEFORE installing any snapshot. No old marker can silently recreate lost state.
        Files.write(consumed, (resetId + "\n" + sha256(assignmentFile) + "\n").getBytes(StandardCharsets.UTF_8),
                StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);
        for (String node : new String[] {"TradeSvrA", "TradeSvrB"}) {
            TradeSnapshotStore store = new TradeSnapshotStore();
            Field field = TradeSnapshotStore.class.getDeclaredField("path");
            field.setAccessible(true); field.set(store, root.resolve("data/" + node + "/snapshot").toString());
            for (int partition = 0; partition < 256; partition++) {
                String id = String.format("P%03d", partition);
                TradePartitionSnapshot snapshot = new TradePartitionSnapshot();
                // Current live applier has no cash-v2 ledger component wired. Genesis
                // has no cash results, so use the supported live format (v2), not
                // the candidate-only v3 format which must be rejected without it.
                snapshot.setVersion(TradePartitionSnapshot.CURRENT_VERSION);
                snapshot.setPartitionId(id); snapshot.setEpoch(1L);
                snapshot.setSnapshotId("genesis-" + resetId + "-" + node + "-" + id);
                snapshot.setCreatedAt(System.currentTimeMillis());
                // All sequence counters are zero and ALL business sections stay empty.
                // New identities and funds must subsequently use the normal APIs/journal.
                store.save(snapshot);
                TradePartitionSnapshot loaded = store.load(id);
                require(loaded != null && loaded.getSnapshotSeq() == 0 && loaded.getCommittedStateSeq() == 0
                        && loaded.getCommittedStateEpoch() == 0
                        && loaded.getLocations().isEmpty() && loaded.getBalances().isEmpty()
                        && loaded.getPositions().isEmpty() && loaded.getOpenOrders().isEmpty()
                        && loaded.getAccountConfigs().isEmpty() && loaded.getSymbolParas().isEmpty()
                        && loaded.getCashRequestResults().isEmpty(), "genesis read-back mismatch");
                // Exercise the real live startup parser, including its no-cash-ledger gate.
                TradeRecoveryApplier applier = new TradeRecoveryApplier();
                Field authoritative = TradeRecoveryApplier.class.getDeclaredField("authoritativeRecovery");
                authoritative.setAccessible(true); authoritative.set(applier, true);
                try (TradeSnapshotStore.RecoverySnapshot handle = store.openRecovery(id)) {
                    TradeRecoveryPlan plan = new TradeRecoveryPlan(id, 1L, handle.getSnapshot(),
                            java.util.Collections.emptyList(), 0L, 0L).withRecoverySnapshot(handle);
                    require(applier.prepareLifecycle(plan, () -> { }).hasBaseline(), "live parser rejected baseline");
                }
            }
        }
        Files.write(resetFile.resolveSibling(resetFile.getFileName() + ".genesis-complete"),
                (resetId + "\nsnapshots=512\n").getBytes(StandardCharsets.UTF_8), StandardOpenOption.CREATE_NEW);
        System.out.println("GENESIS_PASS nodes=2 partitions=256 snapshots=512 moneyRows=0 databaseReads=0");
    }

    public static void main(String[] args) throws Exception {
        require(args.length == 3, "usage: runtimeRoot reset-proof.json actual-assignments.jsonl");
        Path root = Paths.get(args[0]);
        require("/data/dc-saas-runtime".equals(root.toString()) || "/opt/dc-saas-runtime".equals(root.toString()),
                "unsupported standalone test runtime root");
        bootstrap(root, Paths.get(args[1]), Paths.get(args[2]));
    }
}
