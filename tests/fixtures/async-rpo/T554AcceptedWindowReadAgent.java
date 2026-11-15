import java.lang.instrument.Instrumentation;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;

/** Read the existing authenticated Common accepted-window API only.
 * No transformer, dispatch, WAL write, ACK, READY or recovery action. */
public final class T554AcceptedWindowReadAgent {
    public static void agentmain(String arguments, Instrumentation unused) throws Exception {
        String[] args=arguments.split(",",-1);
        if(args.length!=5 ||!args[1].matches("P[0-9]{3}")
                ||!("TradeSvr".equals(args[3]) ||"OrderSvr".equals(args[3]))
                ||!args[4].matches("[a-f0-9]{64}"))throw new IllegalArgumentException("Explicit bounded source required");
        Path output=Paths.get(args[0]);long epoch=Long.parseLong(args[2]);
        if(!output.isAbsolute() ||Files.exists(output) ||epoch<=0)
            throw new IllegalArgumentException("New absolute output and positive epoch required");
        Class<?> type=Class.forName("com.app.common.replication.CommonCertifiedNodeRuntime");
        Path jar=Paths.get(type.getProtectionDomain().getCodeSource().getLocation().toURI());
        byte[] digest=MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(jar));
        StringBuilder sha=new StringBuilder();for(byte value:digest)sha.append(String.format("%02x",value&255));
        if(!args[4].equals(sha.toString()))throw new SecurityException("Actual Common JAR differs");
        Object runtime=Class.forName("com.app.dc.signal.SpringContextHolder")
                .getMethod("getBean",Class.class).invoke(null,type);
        if(!args[3].equals(type.getMethod("serviceName").invoke(runtime)))
            throw new SecurityException("Wrong actual service runtime");
        Object registry=type.getMethod("requireCertifiedBusinessRegistry").invoke(runtime);
        Method read=registry.getClass().getMethod("readAcceptedCommittedWindow",String.class,long.class,long.class,int.class);
        Object window=read.invoke(registry,args[1],epoch,0L,256);
        Class<?> windowType=window.getClass();
        long actualEpoch=(Long)windowType.getField("epoch").get(window);
        long head=(Long)windowType.getField("committedHead").get(window);
        List<?> frames=(List<?>)windowType.getField("frames").get(window);
        if(!args[1].equals(windowType.getField("partition").get(window))
                ||actualEpoch!=epoch ||head<0 ||head>256 ||frames.size()!=head)
            throw new IllegalStateException("Incomplete bounded authenticated window");
        StringBuilder result=new StringBuilder("SCOPE COMMON_ACCEPTED_BYTES_NOT_QUORUM_OR_NEW_AUTHORITY\n");
        result.append("COMMON ").append(sha).append('\n');
        result.append("HEAD ").append(args[1]).append(' ').append(epoch).append(' ').append(head).append('\n');
        long expected=0,total=0;
        for(Object frame:frames){
            Class<?> frameType=frame.getClass();
            long e=(Long)frameType.getField("epoch").get(frame),seq=(Long)frameType.getField("sequence").get(frame);
            byte[] bytes=(byte[])frameType.getMethod("bytes").invoke(frame);
            total+=bytes.length;
            if(e!=epoch ||seq!=++expected ||bytes.length==0 ||total>1024*1024)
                throw new IllegalStateException("Wrong source coordinates or exceeded read budget");
            result.append("FRAME ").append(e).append(' ').append(seq).append(' ')
                    .append(Base64.getEncoder().encodeToString(bytes)).append('\n');
        }
        Object check=read.invoke(registry,args[1],epoch,head,1);
        if((Long)windowType.getField("epoch").get(check)!=epoch
                ||(Long)windowType.getField("committedHead").get(check)!=head)
            throw new IllegalStateException("Accepted head changed during observation");
        Files.write(output,result.toString().getBytes(StandardCharsets.US_ASCII),
                StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE);
    }
}
