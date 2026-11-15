import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

/** Standalone fault tool self-test. No business service, state or Common WAL. */
public final class T554CommonReplicationPauseAgentTest {
    public static void main(String[] args)throws Exception {
        Path parent=Files.createTempDirectory("t554-replication-fault-selftest-");
        ThreadPoolExecutor pool=pool(8);
        try{
            pool.prestartAllCoreThreads();
            Path requested=parent.resolve("requested");
            T554CommonReplicationPauseAgent.arm(requested,2000);
            CountDownLatch work=new CountDownLatch(1);pool.execute(work::countDown);
            if(work.await(100,TimeUnit.MILLISECONDS))throw new AssertionError("Paused worker ran a copy task");
            Files.createFile(requested.resolve("resume.request"));
            if(!work.await(1,TimeUnit.SECONDS))throw new AssertionError("Explicit release failed");
            status(requested,"RESUMED replication=8 reason=requested");
            Path timeout=parent.resolve("timeout");T554CommonReplicationPauseAgent.arm(timeout,500);
            CountDownLatch timed=new CountDownLatch(1);pool.execute(timed::countDown);
            if(!timed.await(2,TimeUnit.SECONDS))throw new AssertionError("Deadline release failed");
            status(timeout,"RESUMED replication=8 reason=deadline");
        }finally{pool.shutdownNow();if(!pool.awaitTermination(2,TimeUnit.SECONDS))throw new AssertionError("Worker stayed suspended");}
        pool=pool(7);
        try{
            pool.prestartAllCoreThreads();
            try{T554CommonReplicationPauseAgent.arm(parent.resolve("incomplete"),500);
                throw new AssertionError("Incomplete group accepted");}
            catch(IllegalStateException expected){
                CountDownLatch live=new CountDownLatch(1);pool.execute(live::countDown);
                if(!live.await(1,TimeUnit.SECONDS))throw new AssertionError("Rejected setup suspended workers");
            }
        }finally{pool.shutdownNow();pool.awaitTermination(2,TimeUnit.SECONDS);}
        System.out.println("T554_REPLICATION_FAULT_REQUESTED_DEADLINE_AND_REJECTED_SETUP_SELFTEST_PASS");
    }
    private static ThreadPoolExecutor pool(int count){
        return new ThreadPoolExecutor(count,count,0,TimeUnit.MILLISECONDS,new ArrayBlockingQueue<>(16),task->{
            Thread thread=new Thread(task,"common-certified-async-replication");thread.setDaemon(true);return thread;
        });
    }
    private static void status(Path root,String expected)throws Exception {
        for(int i=0;i<100;i++){
            if(expected.equals(new String(Files.readAllBytes(root.resolve("status")),StandardCharsets.US_ASCII).trim()))return;
            Thread.sleep(10);
        }
        throw new AssertionError("Release marker missing");
    }
}
