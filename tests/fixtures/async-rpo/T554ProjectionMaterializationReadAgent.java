import java.lang.instrument.Instrumentation;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;

/** Read the live materialization policy; no transformer or application mutation. */
public final class T554ProjectionMaterializationReadAgent {
    public static void agentmain(String output, Instrumentation unused) throws Exception {
        Path destination=Paths.get(output);
        if(!destination.isAbsolute()||Files.exists(destination))throw new IllegalArgumentException();
        Class<?> holder=Class.forName("com.app.dc.signal.SpringContextHolder");
        Class<?> type=Class.forName("com.app.dc.projection.OrderProjectionService");
        Object service=holder.getMethod("getBean",Class.class).invoke(null,type);
        Field policy=type.getDeclaredField("saveDemo");policy.setAccessible(true);
        MessageDigest hash=MessageDigest.getInstance("SHA-256");
        try(java.io.InputStream in=type.getResourceAsStream("OrderProjectionService.class")){
            byte[] buffer=new byte[16384];
            for(int n;(n=in.read(buffer))!=-1;)hash.update(buffer,0,n);
        }
        StringBuilder digest=new StringBuilder();
        for(byte value:hash.digest())digest.append(String.format(java.util.Locale.ROOT,"%02x",value&255));
        Files.write(destination,("save_demo="+policy.getBoolean(service)+"\nclass_sha256="+digest+"\n")
                .getBytes(StandardCharsets.US_ASCII),StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE);
    }
}
