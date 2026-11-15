import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.time.Instant;
import java.util.*;
import jdk.jfr.consumer.*;

/** Stream existing JFR events through the JDK consumer API. Never attaches
 * to a JVM and never serializes object values, addresses or file paths. */
public final class T554JfrCompactReader {
    private static final Set<String> EVENTS = new HashSet<>(Arrays.asList(
        "jdk.ExecutionSample", "jdk.NativeMethodSample", "jdk.JavaMonitorEnter", "jdk.JavaMonitorWait",
        "jdk.ThreadPark", "jdk.FileRead", "jdk.FileWrite", "jdk.SocketRead", "jdk.SocketWrite",
        "jdk.GarbageCollection", "jdk.GCPhasePause", "jdk.DataLoss"));
    private static String method(RecordedFrame frame) {
        RecordedMethod method=frame.getMethod();
        return method==null?"NO_RECORDED_METHOD":method.getType().getName().replace('/','.')+"."+method.getName();
    }
    private static String safe(String value) {
        if(value.length()>2048 ||value.indexOf('\t')>=0 ||value.indexOf('\n')>=0 ||value.indexOf('\r')>=0)
            throw new IllegalArgumentException("Unbounded or noncompact method metadata");
        return value;
    }
    public static void main(String[] args)throws Exception {
        if(args.length!=3)throw new IllegalArgumentException("Recording, start and end epoch milliseconds required");
        Path source=Paths.get(args[0]);
        if(!Files.isRegularFile(source) ||Files.size(source)>80L*1024*1024)
            throw new IllegalArgumentException("Bounded original JFR file required");
        Instant since=Instant.ofEpochMilli(Long.parseLong(args[1])),until=Instant.ofEpochMilli(Long.parseLong(args[2]));
        if(!since.isBefore(until))throw new IllegalArgumentException("Positive exact observation window required");
        try(RecordingFile recording=new RecordingFile(source);
            BufferedWriter output=new BufferedWriter(new OutputStreamWriter(System.out,StandardCharsets.UTF_8),65536)) {
            long read=0,selected=0;
            output.write("T554_JFR_COMPACT_V2\n");
            while(recording.hasMoreEvents()){
                if(++read>2000000)throw new IOException("Original event count exceeds the read budget");
                RecordedEvent event=recording.readEvent();String type=event.getEventType().getName();
                if(!EVENTS.contains(type))continue;
                Instant start=event.getStartTime(),end=event.getEndTime();
                boolean instant=start.equals(end);
                if(!"jdk.DataLoss".equals(type) &&(instant
                    ?start.isBefore(since)||!start.isBefore(until)
                    :!start.isBefore(until)||!end.isAfter(since)))continue;
                if(++selected>200000)throw new IOException("Selected event count exceeds the read budget");
                String leaf="NO_RECORDED_STACK",caller=leaf;
                List<String> applicationPath=new ArrayList<>();
                RecordedStackTrace trace=event.getStackTrace();
                if(trace!=null){
                    List<RecordedFrame> frames=trace.getFrames();
                    if(!frames.isEmpty()){leaf=method(frames.get(0));caller=leaf;}
                    for(int n=0;n<Math.min(24,frames.size());n++){
                        String name=method(frames.get(n));
                        if(name.startsWith("com.app.common.") ||name.startsWith("com.app.dc.")){
                            if(applicationPath.isEmpty())caller=name;
                            if(applicationPath.size()<8)applicationPath.add(name);
                        }
                    }
                }
                String category="";
                if(type.startsWith("jdk.File")){
                    String path=event.hasField("path")?event.getString("path"):null;
                    if(path==null)path="";
                    category=path.contains("/log/")?"APPLICATION_LOG":path.endsWith(".wal")?"WAL":
                        path.contains("commit")||path.contains(".pending")?"COMMIT_METADATA":"OTHER_FILE_OR_STDIO";
                }
                long lost="jdk.DataLoss".equals(type)&&event.hasField("amount")?event.getLong("amount"):0;
                long bytes=type.equals("jdk.FileRead")&&event.hasField("bytesRead")?event.getLong("bytesRead"):
                    type.equals("jdk.FileWrite")&&event.hasField("bytesWritten")?event.getLong("bytesWritten"):0;
                RecordedThread thread=event.getThread();
                long threadId=thread==null?0:thread.getJavaThreadId();
                output.write(type+"\t"+start+"\t"+event.getDuration().toNanos()+"\t"+
                    safe(leaf)+"\t"+safe(caller)+"\t"+category+"\t"+lost+"\t"+Math.max(0,bytes)+"\t"+
                    threadId+"\t"+safe(String.join(" > ",applicationPath))+"\n");
            }
            output.write("END\t"+read+"\t"+selected+"\n");
        }
    }
}
