import java.lang.instrument.Instrumentation;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.Map;

/** Cached scalar state only. No locks, WAL reads, dispatch or recovery. */
public final class T554LocalWriterFlagsReadAgent {
    private static Object field(Object value,String name)throws Exception{
        for(Class<?> type=value.getClass();type!=null;type=type.getSuperclass()){
            try{Field found=type.getDeclaredField(name);found.setAccessible(true);return found.get(value);}
            catch(NoSuchFieldException absent){}
        }
        throw new NoSuchFieldException(name);
    }
    public static void agentmain(String argument,Instrumentation unused)throws Exception{
        String[] args=argument.split(",",-1);
        if(args.length!=3 ||!args[1].matches("P[0-9]{3}") ||!args[2].matches("[a-f0-9]{64}"))
            throw new IllegalArgumentException("Explicit partition and actual Common hash required");
        Path output=Paths.get(args[0]);
        if(!output.isAbsolute() ||Files.exists(output))throw new IllegalArgumentException("New absolute output required");
        Class<?> type=Class.forName("com.app.common.replication.CommonCertifiedNodeRuntime");
        Path jar=Paths.get(type.getProtectionDomain().getCodeSource().getLocation().toURI());
        StringBuilder sha=new StringBuilder();
        for(byte b:MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(jar)))sha.append(String.format("%02x",b&255));
        if(!args[2].equals(sha.toString()))throw new SecurityException("Wrong actual Common bytes");
        Object runtime=Class.forName("com.app.dc.signal.SpringContextHolder").getMethod("getBean",Class.class).invoke(null,type);
        Object registry=type.getMethod("requireCertifiedBusinessRegistry").invoke(runtime);
        Object local=((Map<?,?>)field(registry,"localBoundaries")).get(args[1]);
        StringBuilder result=new StringBuilder("SCOPE READ_ONLY_CACHED_SCALARS_NOT_AUTHORITY\n");
        result.append("COMMON ").append(sha).append(" PARTITION ").append(args[1]).append('\n');
        if(local==null)result.append("local_present=false\n");
        else{
            for(String key:new String[]{"closed","poisoned","duringApply","frozenForStrictRearm","epoch"})
                result.append("local.").append(key).append('=').append(field(local,key)).append('\n');
            Object wal=field(local,"wal");
            for(String key:new String[]{"closed","poisoned","forcedSequence","lastSequence","pendingSequence"})
                result.append("wal.").append(key).append('=').append(field(wal,key)).append('\n');
            Object store=field(local,"committedLocalHead");
            if(store!=null){Object head=field(store,"current");
                if(head!=null)result.append("cached_published_sequence=").append(field(head,"sequence")).append('\n');}
        }
        Files.write(output,result.toString().getBytes(StandardCharsets.US_ASCII),StandardOpenOption.CREATE_NEW);
    }
}
