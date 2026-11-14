import java.lang.instrument.Instrumentation;
import java.lang.reflect.Field;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.util.Map;

/** Read-only installed-role census. No class transformer, ACK, election or data write. */
public final class T554CommonPhysicalCensusReadAgent {
    private static Object field(Object value, String name) throws Exception {
        Field member = value.getClass().getDeclaredField(name);
        member.setAccessible(true);
        return member.get(value);
    }
    private static String failure(Throwable error) {
        if (error instanceof InvocationTargetException) error = error.getCause();
        String message = String.valueOf(error.getMessage()).replace('\n', ' ').replace('\r', ' ');
        return error.getClass().getSimpleName() + ":" + message.substring(0, Math.min(180, message.length()));
    }
    public static void agentmain(String output, Instrumentation unused) throws Exception {
        Path destination = Paths.get(output);
        if (!destination.isAbsolute() || Files.exists(destination)) throw new IllegalArgumentException();
        Class<?> holder = Class.forName("com.app.dc.signal.SpringContextHolder");
        Class<?> type = Class.forName("com.app.common.replication.CommonCertifiedNodeRuntime");
        Object runtime = holder.getMethod("getBean", Class.class).invoke(null, type);
        String node = (String) field(runtime, "node");
        Object control = field(runtime, "verifiedNodeControl");
        Method censusMethod = control.getClass().getMethod("requireCertifiedPartitionCensus");
        Map<?,?> census = (Map<?,?>) censusMethod.invoke(control);
        Method role = type.getMethod("requireAuthenticatedPartitionRole", String.class);
        Method writer = type.getMethod("requireAuthenticatedBusinessWriter", String.class);
        int roles = 0, writers = 0, expectedWriters = 0;
        StringBuilder failures = new StringBuilder();
        for (int index = 0; index < 256; index++) {
            String partition = String.format(java.util.Locale.ROOT, "P%03d", index);
            try { role.invoke(runtime, partition);roles++; }
            catch (Throwable rejected) { failures.append("role_failure=").append(partition).append(' ').append(failure(rejected)).append('\n'); }
            Object position = census.get(partition);
            if (position != null && node.equals(position.getClass().getField("primary").get(position))) {
                expectedWriters++;
                try { writer.invoke(runtime, partition);writers++; }
                catch (Throwable rejected) { failures.append("writer_failure=").append(partition).append(' ').append(failure(rejected)).append('\n'); }
            }
        }
        StringBuilder report = new StringBuilder();
        report.append("node=").append(node).append('\n');
        report.append("role_ok=").append(roles).append('\n');
        report.append("writer_ok=").append(writers).append('\n');
        report.append("expected_writers=").append(expectedWriters).append('\n');
        synchronized (runtime) {
            report.append("opened_partitions=").append(((Map<?,?>) field(runtime,"partitions")).size()).append('\n');
            report.append("reservations=").append(((Map<?,?>) field(runtime,"restartRecoveries")).size()).append('\n');
        }
        report.append(failures);
        Files.write(destination, report.toString().getBytes(StandardCharsets.UTF_8),
                StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);
    }
}
