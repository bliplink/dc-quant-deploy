import java.lang.instrument.Instrumentation;
import java.lang.management.*;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;

/** Cached flags and zero-depth thread metadata only. No stack traces,
 * monitor ownership dumps, transformer, WAL access or recovery actions. */
public final class T554CommonRecoveryLockReadAgent {
    private static Object field(Object target, String name) throws Exception {
        for (Class<?> type = target.getClass(); type != null; type = type.getSuperclass()) {
            try { Field f = type.getDeclaredField(name); f.setAccessible(true); return f.get(target); }
            catch (NoSuchFieldException absent) { }
        }
        throw new NoSuchFieldException(name);
    }
    private static Object bean(String name) throws Exception {
        return Class.forName("com.app.dc.signal.SpringContextHolder").getMethod("getBean", Class.class)
            .invoke(null, Class.forName(name));
    }
    public static void agentmain(String argument, Instrumentation unused) throws Exception {
        Path path = Paths.get(argument);
        if (!path.isAbsolute() || Files.exists(path)) throw new IllegalArgumentException("New absolute output required");
        Object binding = bean("com.app.common.replication.CommonCertifiedFirstReadyE2NodeBinding");
        Object returns = field(binding, "returns");
        StringBuilder out = new StringBuilder("scope=READ_ONLY_FLAGS_AND_THREAD_METADATA_ZERO_STACK_DEPTH\n");
        if (returns != null) {
            out.append("retained_physically_retired=").append(field(returns, "retainedPhysicallyRetired")).append('\n');
            out.append("retained_stage_present=").append(field(returns, "retainedStage") != null).append('\n');
            out.append("return_progress=").append(field(returns, "progress")).append('\n');
        }
        ThreadMXBean threads = ManagementFactory.getThreadMXBean();
        ThreadInfo[] info = threads.getThreadInfo(threads.getAllThreadIds(), 0);
        Map<Long,ThreadInfo> indexed = new HashMap<>();
        Set<Long> selected = new HashSet<>();
        for (ThreadInfo row : info) if (row != null) {
            indexed.put(row.getThreadId(), row);
            String name = row.getThreadName().toLowerCase(Locale.ROOT);
            if (name.contains("common-witnessed-return") || name.contains("common-certified-snapshot")
                    || name.contains("common-periodic") || name.contains("common-node-control"))
                selected.add(row.getThreadId());
        }
        for (int depth = 0; depth < 8; depth++) {
            Set<Long> owners = new HashSet<>();
            for (Long id : selected) {
                ThreadInfo row = indexed.get(id);
                if (row != null && row.getLockOwnerId() > 0) owners.add(row.getLockOwnerId());
            }
            if (!selected.addAll(owners)) break;
        }
        for (Long id : new TreeSet<>(selected)) {
            ThreadInfo row = indexed.get(id);
            if (row == null) continue;
            if (row.getStackTrace().length != 0) throw new IllegalStateException("Unexpected stack capture");
            out.append("THREAD id=").append(id).append(" name=").append(row.getThreadName())
                .append(" state=").append(row.getThreadState()).append(" lock=").append(row.getLockName())
                .append(" owner=").append(row.getLockOwnerId()).append(" owner_name=")
                .append(row.getLockOwnerName()).append('\n');
        }
        Files.write(path, out.toString().getBytes(StandardCharsets.UTF_8),
                    StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);
    }
}
