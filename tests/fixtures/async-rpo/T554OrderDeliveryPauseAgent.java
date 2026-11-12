import java.lang.instrument.Instrumentation;
import java.lang.management.ManagementFactory;
import java.lang.management.ThreadInfo;
import java.lang.management.ThreadMXBean;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.FutureTask;
import java.util.concurrent.ScheduledThreadPoolExecutor;

/** Bounded test fault only. Pauses idle settlement delivery workers while
 * ordinary Common WAL replication continues. No class transformer, business
 * field write, ACK, role, Epoch, or recovery operation is performed. */
@SuppressWarnings("deprecation")
public final class T554OrderDeliveryPauseAgent {
    private static final String WORKER = "order-committed-match-delivery";
    private static final String SCHEDULED_TARGET = "com.app.dc.service.state.OrderSignedMatchDeliveryWorker";
    private static final AtomicBoolean ACTIVE = new AtomicBoolean();
    private static final ThreadMXBean THREADS = ManagementFactory.getThreadMXBean();

    public static void agentmain(String arguments, Instrumentation unused) throws Exception {
        String[] fields = arguments.split(",", -1);
        if (fields.length != 2) throw new IllegalArgumentException("Expected new control directory and hold milliseconds");
        Path root = Paths.get(fields[0]);
        long holdMillis = Long.parseLong(fields[1]);
        arm(root, holdMillis, SCHEDULED_TARGET);
    }

    static void arm(Path root, long holdMillis, String scheduledTarget) throws Exception {
        if (!root.isAbsolute() || Files.exists(root) || holdMillis < 500 || holdMillis > 30000)
            throw new IllegalArgumentException("Expected a new absolute directory and a bounded hold");
        if (!ACTIVE.compareAndSet(false, true)) throw new IllegalStateException("A delivery fault is already active");
        List<Thread> suspended = new ArrayList<>();
        int deliveries = 0;
        int schedulers = 0;
        boolean handedOff = false;
        try {
            Files.createDirectory(root);
            long searchDeadline = System.nanoTime() + java.util.concurrent.TimeUnit.SECONDS.toNanos(3);
            while (suspended.size() < 3 && System.nanoTime() < searchDeadline) {
                List<Thread> candidates = new ArrayList<>(Thread.getAllStackTraces().keySet());
                candidates.sort(Comparator.comparingLong(Thread::getId));
                for (Thread candidate : candidates) {
                    if (suspended.contains(candidate)) continue;
                    boolean delivery = deliveries < 2 && WORKER.equals(candidate.getName());
                    boolean scheduler = schedulers == 0 && ownsRetrySchedule(candidate, scheduledTarget);
                    if ((!delivery && !scheduler) || !idleWithoutLocks(candidate)) continue;
                    candidate.suspend();
                    if (idleWithoutLocks(candidate)) {
                        suspended.add(candidate);
                        if (delivery) deliveries++;
                        else schedulers++;
                    } else candidate.resume();
                    if (suspended.size() == 3) break;
                }
                if (suspended.size() < 3) Thread.sleep(10);
            }
            if (deliveries != 2 || schedulers != 1)
                throw new IllegalStateException("Two idle delivery workers and their idle retry scheduler are required");
            long deadline = System.nanoTime() + java.util.concurrent.TimeUnit.MILLISECONDS.toNanos(holdMillis);
            write(root, "PAUSED delivery=2 scheduler=1 holdMillis=" + holdMillis);
            Thread release = new Thread(() -> {
                String reason = "deadline";
                try {
                    while (System.nanoTime() < deadline) {
                        if (Files.exists(root.resolve("resume.request"))) {
                            reason = "requested";
                            break;
                        }
                        Thread.sleep(5);
                    }
                } catch (Exception interrupted) {
                    reason = "interrupted";
                } finally {
                    for (Thread worker : suspended) worker.resume();
                    ACTIVE.set(false);
                    try { write(root, "RESUMED delivery=2 scheduler=1 reason=" + reason); }
                    catch (Exception failure) { System.err.println("T554_RPO_DELIVERY_RELEASE_STATUS_WRITE_FAILED"); }
                }
            }, "t554-rpo-delivery-deadline");
            release.setDaemon(true);
            release.start();
            handedOff = true;
        } finally {
            if (!handedOff) {
                for (Thread worker : suspended) worker.resume();
                ACTIVE.set(false);
            }
        }
    }

    private static boolean ownsRetrySchedule(Thread worker, String targetClass) throws Exception {
        Object target = field(worker, "target");
        if (target == null || !target.getClass().getName().equals("java.util.concurrent.ThreadPoolExecutor$Worker"))
            return false;
        Object executor = field(target, "this$0");
        if (!(executor instanceof ScheduledThreadPoolExecutor)) return false;
        ScheduledThreadPoolExecutor scheduled = (ScheduledThreadPoolExecutor) executor;
        if (scheduled.getCorePoolSize() != 1) return false;
        for (Runnable queued : scheduled.getQueue()) {
            if (!(queued instanceof FutureTask)) continue;
            Object callback = field(queued, "callable");
            for (int depth = 0; callback != null && depth < 5; depth++) {
                String type = callback.getClass().getName();
                if (type.equals(targetClass)) return true; // Standalone tool self-test probe.
                if (type.equals("java.util.concurrent.Executors$RunnableAdapter")) callback = field(callback, "task");
                else if (type.equals("org.springframework.scheduling.support.DelegatingErrorHandlingRunnable"))
                    callback = field(callback, "delegate");
                else if (type.equals("org.springframework.scheduling.support.ScheduledMethodRunnable")) {
                    Object bean = field(callback, "target");
                    Method method = (Method) field(callback, "method");
                    return bean.getClass().getName().equals(targetClass) && method.getName().equals("retryOutstanding");
                } else break;
            }
        }
        return false;
    }

    private static Object field(Object instance, String name) throws Exception {
        for (Class<?> type = instance.getClass(); type != null; type = type.getSuperclass()) {
            try {
                Field member = type.getDeclaredField(name);
                member.setAccessible(true);
                return member.get(instance);
            } catch (NoSuchFieldException inherited) {
                // FutureTask.callable is inherited by its scheduled wrapper.
            }
        }
        throw new NoSuchFieldException(name);
    }

    private static boolean idleWithoutLocks(Thread worker) {
        ThreadInfo info = THREADS.getThreadInfo(new long[]{worker.getId()}, true, true)[0];
        if (info == null || info.getLockedMonitors().length != 0 || info.getLockedSynchronizers().length != 0)
            return false;
        for (StackTraceElement frame : info.getStackTrace()) {
            if (frame.getClassName().equals("java.util.concurrent.ThreadPoolExecutor")
                    && frame.getMethodName().equals("getTask")) return true;
        }
        return false;
    }

    private static void write(Path root, String value) throws Exception {
        Path temporary = root.resolve("status.tmp");
        Files.write(temporary, (value + "\n").getBytes(StandardCharsets.US_ASCII));
        Files.move(temporary, root.resolve("status"), StandardCopyOption.ATOMIC_MOVE,
                StandardCopyOption.REPLACE_EXISTING);
    }
}
