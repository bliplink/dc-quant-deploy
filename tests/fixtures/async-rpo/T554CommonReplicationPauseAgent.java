import java.lang.instrument.Instrumentation;
import java.lang.management.ManagementFactory;
import java.lang.management.ThreadInfo;
import java.lang.management.ThreadMXBean;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/** Test-only delivery fault. Stops only eight idle, lock-free existing
 * replication executor threads. No transformer, business/WAL field write,
 * fabricated ACK, role, Epoch or recovery operation. */
@SuppressWarnings("deprecation")
public final class T554CommonReplicationPauseAgent {
    private static final String NAME="common-certified-async-replication";
    private static final ThreadMXBean THREADS=ManagementFactory.getThreadMXBean();
    private static final AtomicBoolean ACTIVE=new AtomicBoolean();

    public static void agentmain(String args,Instrumentation ignored)throws Exception {
        String[] fields=args.split(",",-1);
        if(fields.length!=2)throw new IllegalArgumentException("Expected new directory and hold milliseconds");
        arm(Paths.get(fields[0]),Long.parseLong(fields[1]));
    }

    static void arm(Path root,long holdMillis)throws Exception {
        if(!root.isAbsolute() ||Files.exists(root) ||holdMillis<500 ||holdMillis>10000)
            throw new IllegalArgumentException("Expected new absolute directory and bounded hold");
        if(!ACTIVE.compareAndSet(false,true))throw new IllegalStateException("Replication fault already active");
        List<Thread> paused=new ArrayList<>();boolean handedOff=false;
        try{
            Files.createDirectory(root);
            List<Thread> candidates=workers();
            if(candidates.size()!=8)throw new IllegalStateException("Exactly eight existing replication workers required");
            long search=System.nanoTime()+TimeUnit.SECONDS.toNanos(3);
            while(paused.size()!=8 &&System.nanoTime()<search){
                for(Thread thread:candidates){
                    if(paused.contains(thread) ||!idle(thread))continue;
                    thread.suspend();
                    if(idle(thread))paused.add(thread);else thread.resume();
                }
                if(paused.size()!=8)Thread.sleep(10);
            }
            if(paused.size()!=8)throw new IllegalStateException("All replication workers must be idle and lock-free");
            long deadline=System.nanoTime()+TimeUnit.MILLISECONDS.toNanos(holdMillis);
            write(root,"PAUSED replication=8 holdMillis="+holdMillis);
            Thread release=new Thread(()->{
                String reason="deadline";
                try{
                    while(System.nanoTime()<deadline){
                        if(Files.exists(root.resolve("resume.request"))){reason="requested";break;}
                        Thread.sleep(5);
                    }
                }catch(Exception interrupted){reason="interrupted";}
                finally{
                    for(Thread worker:paused)worker.resume();
                    ACTIVE.set(false);
                    try{write(root,"RESUMED replication=8 reason="+reason);}
                    catch(Exception failure){System.err.println("T554_REPLICATION_FAULT_RELEASE_STATUS_FAILED");}
                }
            },"t554-replication-fault-deadline");
            release.setDaemon(true);release.start();handedOff=true;
        }finally{
            if(!handedOff){for(Thread thread:paused)thread.resume();ACTIVE.set(false);}
        }
    }

    private static List<Thread> workers(){
        ThreadGroup group=Thread.currentThread().getThreadGroup();
        while(group.getParent()!=null)group=group.getParent();
        Thread[] threads=new Thread[4096];int count=group.enumerate(threads,true);
        if(count==threads.length)throw new IllegalStateException("Thread inventory exceeds bounded test capture");
        List<Thread> result=new ArrayList<>();
        for(int i=0;i<count;i++)if(NAME.equals(threads[i].getName()))result.add(threads[i]);
        result.sort(Comparator.comparingLong(Thread::getId));return result;
    }

    private static boolean idle(Thread thread){
        ThreadInfo info=THREADS.getThreadInfo(new long[]{thread.getId()},true,true)[0];
        if(info==null ||info.getLockedMonitors().length!=0 ||info.getLockedSynchronizers().length!=0)return false;
        for(StackTraceElement frame:info.getStackTrace())
            if(frame.getClassName().equals("java.util.concurrent.ThreadPoolExecutor")
                    &&frame.getMethodName().equals("getTask"))return true;
        return false;
    }

    private static void write(Path root,String value)throws Exception {
        Path pending=root.resolve("status.pending");
        Files.write(pending,(value+"\n").getBytes(StandardCharsets.US_ASCII));
        Files.move(pending,root.resolve("status"),StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
    }
}
