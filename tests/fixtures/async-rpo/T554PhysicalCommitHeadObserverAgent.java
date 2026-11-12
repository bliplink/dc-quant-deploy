import java.lang.instrument.Instrumentation;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.util.Map;

/** Test-only read observer. Calls Common's existing authenticated physical
 * head reader. Never writes a business field, WAL, ACK, role or certificate. */
public final class T554PhysicalCommitHeadObserverAgent {
    public static void agentmain(String arguments, Instrumentation unused) throws Exception {
        String[] fields = arguments.split(",", -1);
        if (fields.length != 5) throw new IllegalArgumentException("Expected output, partition, epoch, head, SHA");
        Path output = Paths.get(fields[0]);
        if (!output.isAbsolute() || Files.exists(output))
            throw new IllegalArgumentException("Expected a new absolute observer output");
        String status;
        try {
            Class<?> runtimeType = Class.forName("com.app.common.replication.CommonCertifiedNodeRuntime");
            Class<?> holder = Class.forName("com.app.dc.signal.SpringContextHolder");
            Object runtime = holder.getMethod("getBean", Class.class).invoke(null, runtimeType);
            status = observe(runtime, fields[1], Long.parseLong(fields[2]),
                    Long.parseLong(fields[3]), fields[4]);
        } catch (Exception unavailable) {
            // No raw exception text, business bytes, identities or credentials.
            status = "WAIT failure=" + unavailable.getClass().getSimpleName();
        }
        Files.write(output, (status + "\n").getBytes(StandardCharsets.US_ASCII),
                StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);
    }

    static String observe(Object runtime, String partition, long epoch, long sequence, String sha)
            throws Exception {
        if (runtime == null || !partition.matches("P[0-9]{3}") || epoch <= 0 || sequence <= 0
                || !sha.matches("[a-f0-9]{64}"))
            throw new IllegalArgumentException("Exact live Common physical head required");
        Map<?, ?> partitions = (Map<?, ?>) field(runtime, "partitions");
        Object physical = partitions.get(partition);
        if (physical == null) return "WAIT physical=missing";
        Method pending = physical.getClass().getDeclaredMethod("hasPendingAsyncReplication");
        pending.setAccessible(true);
        if (Boolean.TRUE.equals(pending.invoke(physical))) return "WAIT pending=true";
        // This production method verifies original WAL, RSA CommitIndex,
        // custody and both persisted physical custody receipts itself.
        Object certificate = physical.getClass().getMethod("requireAuthenticatedPhysicalCommitHead").invoke(physical);
        if (Boolean.TRUE.equals(pending.invoke(physical))) return "WAIT pending=true";
        long actualEpoch = (Long) field(certificate, "epoch");
        long actualSequence = (Long) field(certificate, "committedSequence");
        String actualSha = (String) field(certificate, "commitPrefixSha256");
        if (actualEpoch != epoch || actualSequence != sequence || !sha.equals(actualSha))
            return "WAIT exactHead=false";
        return "READY epoch=" + epoch + " sequence=" + sequence + " sha256=" + sha + " pending=false";
    }

    private static Object field(Object instance, String name) throws Exception {
        for (Class<?> type = instance.getClass(); type != null; type = type.getSuperclass()) {
            try {
                Field field = type.getDeclaredField(name);
                field.setAccessible(true);
                return field.get(instance);
            } catch (NoSuchFieldException inherited) {
                // Read inherited fields without changing any runtime state.
            }
        }
        throw new NoSuchFieldException(name);
    }
}
