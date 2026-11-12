import java.util.Collections;
import java.util.Map;

public final class T554PhysicalCommitHeadObserverAgentTest {
    private static final String SHA = String.join("", Collections.nCopies(64, "a"));
    public static final class Certificate {
        public long epoch = 2, committedSequence = 7;
        public String commitPrefixSha256 = SHA;
    }
    public static final class Physical {
        boolean pending;
        int reads;
        final Certificate certificate = new Certificate();
        boolean hasPendingAsyncReplication() { return pending; }
        public Certificate requireAuthenticatedPhysicalCommitHead() {
            reads++;
            return certificate;
        }
    }
    public static final class Runtime {
        final Map<String, Physical> partitions;
        Runtime(Physical physical) { partitions = Collections.singletonMap("P007", physical); }
    }
    public static void main(String[] ignored) throws Exception {
        Physical physical = new Physical();
        Runtime runtime = new Runtime(physical);
        physical.pending = true;
        require("WAIT pending=true".equals(observe(runtime)), "pending cannot be mistaken for complete");
        require(physical.reads == 0, "pending observer must not block a physical commit");
        physical.pending = false;
        require(observe(runtime).startsWith("READY epoch=2 sequence=7"), "exact authenticated head required");
        physical.certificate.committedSequence = 6;
        require("WAIT exactHead=false".equals(observe(runtime)), "stale certified head rejected");
        physical.certificate.committedSequence = 7;
        physical.certificate.commitPrefixSha256 = String.join("", Collections.nCopies(64, "b"));
        require("WAIT exactHead=false".equals(observe(runtime)), "divergent certified prefix rejected");
        require("WAIT physical=missing".equals(T554PhysicalCommitHeadObserverAgent.observe(runtime, "P008", 2, 7, SHA)),
                "missing partition rejected");
        System.out.println("T554_PHYSICAL_HEAD_READ_OBSERVER_SELF_TEST_PASS");
    }
    private static String observe(Runtime runtime) throws Exception {
        return T554PhysicalCommitHeadObserverAgent.observe(runtime, "P007", 2, 7, SHA);
    }
    private static void require(boolean condition, String reason) {
        if (!condition) throw new AssertionError(reason);
    }
}
