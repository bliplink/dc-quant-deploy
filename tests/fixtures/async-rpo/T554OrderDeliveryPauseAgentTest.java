import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

/** Tool self-test, without business services or Common state. */
public final class T554OrderDeliveryPauseAgentTest {
    public static void main(String[] arguments) throws Exception {
        Path parent = Files.createTempDirectory("t554-rpo-agent-selftest-");
        ThreadPoolExecutor workers = pool(2);
        ScheduledThreadPoolExecutor scheduler = new ScheduledThreadPoolExecutor(1);
        ScheduledProbe probe = new ScheduledProbe();
        try {
            workers.prestartAllCoreThreads();
            scheduler.scheduleWithFixedDelay(probe, 0, 20, TimeUnit.MILLISECONDS);
            Path requested = parent.resolve("requested");
            T554OrderDeliveryPauseAgent.arm(requested, 2000, ScheduledProbe.class.getName());
            int ticks = probe.ticks.get();
            CountDownLatch task = new CountDownLatch(1);
            workers.execute(task::countDown);
            if (task.await(100, TimeUnit.MILLISECONDS)) throw new AssertionError("Paused worker executed a task");
            if (probe.ticks.get() != ticks) throw new AssertionError("Retry scheduler remained active");
            Files.createFile(requested.resolve("resume.request"));
            if (!task.await(1, TimeUnit.SECONDS)) throw new AssertionError("Explicit resume did not release workers");
            awaitStatus(requested, "RESUMED delivery=2 scheduler=1 reason=requested");
            Path deadline = parent.resolve("deadline");
            T554OrderDeliveryPauseAgent.arm(deadline, 500, ScheduledProbe.class.getName());
            task = new CountDownLatch(1);
            CountDownLatch timeoutTask = task;
            workers.execute(timeoutTask::countDown);
            if (!task.await(2, TimeUnit.SECONDS)) throw new AssertionError("Automatic deadline did not release workers");
            awaitStatus(deadline, "RESUMED delivery=2 scheduler=1 reason=deadline");
        } finally {
            workers.shutdownNow();
            scheduler.shutdownNow();
            if (!workers.awaitTermination(2, TimeUnit.SECONDS)) throw new AssertionError("Workers stayed suspended");
        }
        workers = pool(1);
        try {
            workers.prestartAllCoreThreads();
            try {
                T554OrderDeliveryPauseAgent.agentmain(parent.resolve("incomplete") + ",500", null);
                throw new AssertionError("An incomplete worker group was accepted");
            } catch (IllegalStateException expected) {
                CountDownLatch released = new CountDownLatch(1);
                workers.execute(released::countDown);
                if (!released.await(1, TimeUnit.SECONDS)) throw new AssertionError("Failed setup left a worker paused");
            }
        } finally {
            workers.shutdownNow();
        }
        System.out.println("T554_DELIVERY_FAULT_EXPLICIT_RESUME_DEADLINE_AND_FAILED_SETUP_SELFTEST_PASS");
    }

    public static final class ScheduledProbe implements Runnable {
        final AtomicInteger ticks = new AtomicInteger();
        public void run() { ticks.incrementAndGet(); }
    }

    private static ThreadPoolExecutor pool(int count) {
        return new ThreadPoolExecutor(count, count, 0L, TimeUnit.MILLISECONDS,
                new ArrayBlockingQueue<>(16), work -> {
                    Thread thread = new Thread(work, "order-committed-match-delivery");
                    thread.setDaemon(true);
                    return thread;
                });
    }

    private static void awaitStatus(Path root, String expected) throws Exception {
        for (int attempt = 0; attempt < 100; attempt++) {
            String actual = new String(Files.readAllBytes(root.resolve("status")), StandardCharsets.US_ASCII).trim();
            if (expected.equals(actual)) return;
            Thread.sleep(10);
        }
        throw new AssertionError("Release proof missing");
    }
}
