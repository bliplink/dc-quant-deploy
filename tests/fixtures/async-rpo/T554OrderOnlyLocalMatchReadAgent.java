import java.lang.instrument.Instrumentation;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.List;
import java.util.Set;
import java.util.TreeSet;

/** Verify the test pair against Common's existing authenticated LOCAL history. */
public final class T554OrderOnlyLocalMatchReadAgent {
    private static Object call(Object target, String method) throws Exception {
        return target.getClass().getMethod(method).invoke(target);
    }

    private static String digest(byte[] bytes) throws Exception {
        StringBuilder result = new StringBuilder();
        for (byte value : MessageDigest.getInstance("SHA-256").digest(bytes)) {
            result.append(String.format("%02x", value & 255));
        }
        return result.toString();
    }

    public static void agentmain(String arguments, Instrumentation unused) throws Exception {
        String[] args = arguments.split(",", -1);
        boolean rearmed = args.length == 8 && args[7].equals("rearmed");
        if ((args.length != 7 && !rearmed) || !args[1].matches("P[0-9]{3}") || !args[3].matches("[A-Z0-9]{6}")
                || !args[4].matches("OO-[A-F0-9]{10}-MAKER") || !args[5].matches("OO-[A-F0-9]{10}-TAKER")
                || !args[6].matches("[a-f0-9]{64}")) {
            throw new IllegalArgumentException("Exact Order-only LOCAL test pair required");
        }
        Path output = Paths.get(args[0]);
        long epoch = Long.parseLong(args[2]);
        if (!output.isAbsolute() || Files.exists(output) || epoch < 3) {
            throw new IllegalArgumentException("New output and witnessed LOCAL Epoch required");
        }
        Class<?> type = Class.forName("com.app.common.replication.CommonCertifiedNodeRuntime");
        Path jar = Paths.get(type.getProtectionDomain().getCodeSource().getLocation().toURI());
        if (!args[6].equals(digest(Files.readAllBytes(jar)))) {
            throw new SecurityException("Actual Common JAR differs");
        }
        Method bean = Class.forName("com.app.dc.signal.SpringContextHolder").getMethod("getBean", Class.class);
        Object runtime = bean.invoke(null, type);
        if (!"OrderSvr".equals(call(runtime, "serviceName"))) {
            throw new SecurityException("Wrong physical service");
        }
        Object permit = null;
        if (!rearmed) {
            Field verifiedControl = type.getDeclaredField("verifiedNodeControl");
            verifiedControl.setAccessible(true);
            Object control = verifiedControl.get(runtime);
            Class<?> policyType = Class.forName("com.app.common.replication.DurableWalAckPolicy");
            Object local = policyType.getField("LOCAL_DURABLE_ASYNC").get(null);
            Method requirePrimary = control.getClass().getMethod("requirePrimary", String.class, long.class, policyType);
            permit = requirePrimary.invoke(control, args[1], epoch, local);
            call(permit, "requireCurrent");
        }

        Class<?> outboxType = Class.forName("com.app.dc.service.state.OrderCertifiedMatchOutbox");
        Object outbox = bean.invoke(null, outboxType);
        List<?> pending = (List<?>) outboxType.getMethod("pendingPartition", String.class).invoke(outbox, args[1]);
        Set<String> expected = new TreeSet<>(Arrays.asList(args[4], args[5]));
        String result = "NO_MATCH\n";
        for (Object item : pending) {
            if ((Long) call(item, "getEpoch") != epoch) {
                continue;
            }
            List<?> reports = (List<?>) call(call(item, "settlement"), "reports");
            if (reports.size() != 2 || !args[3].equals(call(reports.get(0), "getLocation"))
                    || !"BTC003USDT".equals(call(reports.get(0), "getSecurityID"))) {
                continue;
            }
            Set<String> clientIds = new TreeSet<>();
            for (Object report : reports) {
                clientIds.add((String) call(report, "getClOrdID"));
            }
            if (!clientIds.equals(expected)) {
                continue;
            }
            Set<String> executions = new TreeSet<>();
            for (Object report : reports) {
                String execution = (String) call(report, "getExecID");
                if (!args[3].equals(call(report, "getLocation")) || !"BTC003USDT".equals(call(report, "getSecurityID"))
                        || !"Trade".equals(call(report, "getExecType")) || !"Filled".equals(call(report, "getOrdStatus"))
                        || execution == null || !execution.matches("E[a-f0-9]{30}") || !executions.add(execution)) {
                    throw new IllegalStateException("Expected two distinct final executions");
                }
            }
            long seq = (Long) call(item, "getSeq");
            Object registry = call(runtime, "requireCertifiedBusinessRegistry");
            Object frame;
            if (rearmed) {
                Method read = registry.getClass().getMethod("readRearmedLocalCommand", String.class, long.class, long.class);
                frame = read.invoke(registry, args[1], epoch, seq);
            } else {
                Method read = registry.getClass().getMethod("readAcceptedCommittedWindow",
                        String.class, long.class, long.class, int.class);
                Object window = read.invoke(registry, args[1], epoch, seq - 1, 1);
                Class<?> typeOfWindow = window.getClass();
                List<?> frames = (List<?>) typeOfWindow.getField("frames").get(window);
                if (!args[1].equals(typeOfWindow.getField("partition").get(window))
                        || typeOfWindow.getField("epoch").getLong(window) != epoch
                        || typeOfWindow.getField("committedHead").getLong(window) < seq || frames.size() != 1) {
                    throw new SecurityException("The exact match was outside the authenticated LOCAL boundary");
                }
                frame = frames.get(0);
            }
            byte[] accepted = (byte[]) call(frame, "bytes");
            byte[] original = ((String) call(call(item, "originalCommittedFrame"), "encode"))
                    .getBytes(StandardCharsets.UTF_8);
            if (frame.getClass().getField("epoch").getLong(frame) != epoch
                    || frame.getClass().getField("sequence").getLong(frame) != seq || !Arrays.equals(original, accepted)
                    || !result.equals("NO_MATCH\n")) {
                throw new SecurityException("The LOCAL match frame changed or was repeated");
            }
            result = String.join(" ", rearmed ? "REARMED_MATCH" : "LOCAL_MATCH", args[1], Long.toString(epoch), Long.toString(seq),
                    digest(accepted), String.join(" ", executions)) + "\n";
        }
        if (permit != null) call(permit, "requireCurrent");
        Files.write(output, result.getBytes(StandardCharsets.US_ASCII),
                StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);
    }
}
