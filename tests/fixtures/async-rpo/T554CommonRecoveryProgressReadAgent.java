import java.lang.instrument.Instrumentation;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.Map;

/** One bounded observation of cached Common recovery diagnostics only.
 * No monitor acquisition, recovery action, WAL read, transformer or ACK. */
public final class T554CommonRecoveryProgressReadAgent {
    private static Object field(Object target, String name) throws Exception {
        for (Class<?> type = target.getClass(); type != null; type = type.getSuperclass()) {
            try {
                Field field = type.getDeclaredField(name);
                field.setAccessible(true);
                return field.get(target);
            } catch (NoSuchFieldException absent) { }
        }
        throw new NoSuchFieldException(name);
    }
    private static Object bean(String name) throws Exception {
        return Class.forName("com.app.dc.signal.SpringContextHolder")
            .getMethod("getBean", Class.class).invoke(null, Class.forName(name));
    }
    private static String bounded(Object raw) {
        if (raw == null) return "null";
        if (!(raw instanceof String)) return raw.getClass().getName();
        String text = ((String) raw).replace('\n', ' ').replace('\r', ' ');
        return text.substring(0, Math.min(2048, text.length()));
    }
    public static void agentmain(String arguments, Instrumentation unused) throws Exception {
        String[] args = arguments.split(",", -1);
        if (args.length != 2 || !args[1].matches("P[0-9]{3}"))
            throw new IllegalArgumentException("One explicit partition required");
        Path output = Paths.get(args[0]);
        if (!output.isAbsolute() || Files.exists(output))
            throw new IllegalArgumentException("New absolute observation path required");
        Object runtime = bean("com.app.common.replication.CommonCertifiedNodeRuntime");
        // Weak read only: these caches can change concurrently, and cannot
        // authorize any admission, recovery, commit or READY publication.
        Object watch = ((Map<?,?>) field(runtime, "failoverWatches")).get(args[1]);
        StringBuilder result = new StringBuilder("scope=CACHED_RECOVERY_DIAGNOSTIC_NOT_AUTHORITY\n");
        result.append("partition=").append(args[1]).append('\n');
        result.append("watch_present=").append(watch != null).append('\n');
        if (watch != null) {
            result.append("watch_rejection=").append(bounded(field(watch, "latestRejected"))).append('\n');
            result.append("watch_ready=").append(field(watch, "ready")).append('\n');
            result.append("watch_stage_present=").append(field(watch, "stage") != null).append('\n');
        }
        Object binding = bean("com.app.common.replication.CommonCertifiedFirstReadyE2NodeBinding");
        Object returns = field(binding, "returns");
        if (returns != null) {
            result.append("return_progress=").append(bounded(field(returns, "progress"))).append('\n');
            result.append("return_rejection=").append(bounded(field(returns, "lastRejection"))).append('\n');
        }
        Files.write(output, result.toString().getBytes(StandardCharsets.UTF_8),
                    StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);
    }
}
