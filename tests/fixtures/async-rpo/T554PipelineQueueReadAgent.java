import java.lang.instrument.Instrumentation;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;

/** Bounded diagnostic observer only: no transformer, stack walk, WAL read,
 * dispatch, state apply, ACK, READY, or financial mutation. Attach outside
 * qualified pressure windows; the resulting samples are observational. */
public final class T554PipelineQueueReadAgent {
    private static Object field(Object object, String name) throws Exception {
        Class<?> type = object instanceof Class ? (Class<?>) object : object.getClass();
        while (type != null) {
            try {
                Field field = type.getDeclaredField(name);
                field.setAccessible(true);
                return field.get(object instanceof Class ? null : object);
            } catch (NoSuchFieldException absent) {
                type = type.getSuperclass();
            }
        }
        throw new NoSuchFieldException(name);
    }

    static void pool(StringBuilder output, String name, ThreadPoolExecutor pool) {
        output.append(name).append(".pool_size=").append(pool.getPoolSize()).append('\n');
        output.append(name).append(".active=").append(pool.getActiveCount()).append('\n');
        output.append(name).append(".queued=").append(pool.getQueue().size()).append('\n');
        output.append(name).append(".completed=").append(pool.getCompletedTaskCount()).append('\n');
        output.append(name).append(".submitted=").append(pool.getTaskCount()).append('\n');
    }

    private static void deadlines(StringBuilder output, String name, Map<?,?> values, boolean started) {
        long now = System.currentTimeMillis(), oldest = 0, earliest = Long.MAX_VALUE;
        int observed = 0, waiting = 0, expired = 0, permanent = 0;
        for (Object raw : values.values()) {
            if (observed == 10000) break;
            if (!(raw instanceof Long)) throw new IllegalStateException("Unexpected timer value");
            observed++;
            long time = (Long) raw;
            if (started) oldest = Math.max(oldest, Math.max(0, now - time));
            else if (time == Long.MAX_VALUE) permanent++;
            else if (time > now) {
                waiting++;
                earliest = Math.min(earliest, time - now);
            } else expired++;
        }
        output.append(name).append(".map_size=").append(values.size()).append('\n');
        output.append(name).append(".observed=").append(observed).append('\n');
        output.append(name).append(".truncated=").append(values.size() > observed).append('\n');
        if (started) output.append(name).append(".oldest_ms=").append(oldest).append('\n');
        else {
            output.append(name).append(".waiting=").append(waiting).append('\n');
            output.append(name).append(".expired=").append(expired).append('\n');
            output.append(name).append(".permanent=").append(permanent).append('\n');
            output.append(name).append(".earliest_delay_ms=")
                .append(earliest == Long.MAX_VALUE ? -1 : earliest).append('\n');
        }
    }

    public static void agentmain(String arguments, Instrumentation unused) throws Exception {
        String[] args = arguments.split(",", -1);
        if (args.length != 2 || !("OrderSvr".equals(args[1]) || "TradeSvr".equals(args[1])))
            throw new IllegalArgumentException("An explicit OrderSvr/TradeSvr observation is required");
        Path output = Paths.get(args[0]);
        if (!output.isAbsolute() || Files.exists(output))
            throw new IllegalArgumentException("A new absolute diagnostic output is required");
        StringBuilder result = new StringBuilder("scope=WEAKLY_CONSISTENT_READ_ONLY_QUEUES_NOT_COMMIT_OR_PERFORMANCE_PROOF\n");
        result.append("sampled_epoch_ms=").append(System.currentTimeMillis()).append('\n');
        Class<?> boundary = Class.forName("com.app.common.replication.CertifiedBusinessCommandBoundary");
        pool(result, "common_async", (ThreadPoolExecutor) field(boundary, "ASYNC_REPLICATION"));
        if ("OrderSvr".equals(args[1])) {
            Class<?> type = Class.forName("com.app.dc.service.state.OrderSignedMatchDeliveryWorker");
            Object worker = Class.forName("com.app.dc.signal.SpringContextHolder")
                .getMethod("getBean", Class.class).invoke(null, type);
            pool(result, "order_delivery", (ThreadPoolExecutor) field(worker, "immediateDelivery"));
            deadlines(result, "order_inflight", (Map<?,?>) field(worker, "inFlight"), true);
            deadlines(result, "order_retry", (Map<?,?>) field(worker, "nextAttempt"), false);
            Object outbox = field(worker, "outbox");
            result.append("order_outbox.pending_count=")
                .append(outbox.getClass().getMethod("pendingCount").invoke(outbox)).append('\n');
            List<?> pending = (List<?>) outbox.getClass().getMethod("pendingSnapshot", int.class).invoke(outbox, 4096);
            int financial = 0, localCopy = 0;
            for (Object item : pending) {
                if ((Boolean) item.getClass().getMethod("hasLocalSettlementConfirmation").invoke(item)) localCopy++;
                else financial++;
            }
            result.append("order_outbox.observed_financial_unsettled=").append(financial).append('\n');
            result.append("order_outbox.observed_local_copy_pending=").append(localCopy).append('\n');
            result.append("order_outbox.observed_limit=4096\n");
        }
        Files.write(output, result.toString().getBytes(StandardCharsets.US_ASCII),
                    StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 1 || !"--self-test".equals(args[0]))
            throw new IllegalArgumentException("Only --self-test is supported outside attach");
        ThreadPoolExecutor executor = new ThreadPoolExecutor(1, 1, 0L, TimeUnit.MILLISECONDS,
                                                            new ArrayBlockingQueue<Runnable>(4));
        CountDownLatch active = new CountDownLatch(1), release = new CountDownLatch(1);
        try {
            executor.execute(() -> {
                active.countDown();
                try { release.await(); } catch (InterruptedException stop) { Thread.currentThread().interrupt(); }
            });
            if (!active.await(2, TimeUnit.SECONDS)) throw new AssertionError("Fixture did not start");
            StringBuilder idleQueue = new StringBuilder();
            pool(idleQueue, "fixture", executor);
            if (!idleQueue.toString().contains("fixture.active=1\n")
                    || !idleQueue.toString().contains("fixture.queued=0\n"))
                throw new AssertionError("An empty queue must not hide an active callback");
            executor.execute(() -> {});
            StringBuilder queued = new StringBuilder();
            pool(queued, "fixture", executor);
            if (!queued.toString().contains("fixture.queued=1\n")) throw new AssertionError("Queued work missing");
            Map<String, Long> timers = new HashMap<>();
            timers.put("waiting", System.currentTimeMillis() + 30000);
            timers.put("expired", 1L);
            timers.put("permanent", Long.MAX_VALUE);
            StringBuilder retry = new StringBuilder();
            deadlines(retry, "fixture", timers, false);
            for (String expected : Arrays.asList("fixture.waiting=1\n", "fixture.expired=1\n", "fixture.permanent=1\n"))
                if (!retry.toString().contains(expected)) throw new AssertionError("Retry category missing");
            System.out.println("T554_READ_ONLY_PIPELINE_QUEUE_AND_DEADLINE_SELF_TEST_PASS");
        } finally {
            release.countDown();
            executor.shutdownNow();
            if (!executor.awaitTermination(2, TimeUnit.SECONDS)) throw new AssertionError("Fixture did not stop");
        }
    }
}
