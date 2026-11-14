import java.lang.instrument.Instrumentation;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.util.List;

/** Bounded test-only caller of Common's existing public certified history reader.
 * No transformer, business apply, WAL write, ACK, certificate or role mutation. */
public final class T554OriginalCoordinateReadAgent {
    public static void agentmain(String arguments, Instrumentation unused) throws Exception {
        String[] a=arguments.split(",",-1);
        if(a.length!=4 ||!a[1].matches("P[0-9]{3}"))throw new IllegalArgumentException("Bounded historical coordinate required");
        Path output=Paths.get(a[0]);
        if(!output.isAbsolute()||Files.exists(output))throw new IllegalArgumentException("New absolute observer output required");
        long epoch=Long.parseLong(a[2]),seq=Long.parseLong(a[3]);
        if(epoch<2||seq<2)throw new IllegalArgumentException("Positive historical coordinate required");
        String status;
        try {
            Class<?> type=Class.forName("com.app.common.replication.CertifiedBusinessCommandRegistry");
            Object registry=Class.forName("com.app.dc.signal.SpringContextHolder").getMethod("getBean",Class.class).invoke(null,type);
            java.lang.reflect.Method read=type.getMethod("readCertifiedCommittedWindow",String.class,long.class,long.class,int.class);
            Object before=read.invoke(registry,a[1],epoch,seq-2,2);
            Object after=read.invoke(registry,a[1],epoch,seq-1,1);
            status=classify(before,after,epoch,seq);
        }catch(Exception unavailable){status="WAIT failure="+unavailable.getClass().getSimpleName();}
        Files.write(output,(status+"\n").getBytes(StandardCharsets.US_ASCII),StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE);
    }
    static String classify(Object before,Object after,long epoch,long seq)throws Exception{
        long current=(Long)field(after,"epoch");
        if(current<=epoch ||!field(before,"epoch").equals(current))return "WAIT currentEpoch=false";
        List<?> old=(List<?>)field(before,"frames"),next=(List<?>)field(after,"frames");
        if(!next.isEmpty() && ((Long)field(next.get(0),"epoch"))==epoch && ((Long)field(next.get(0),"sequence"))==seq)
            return "INCLUDED origin="+epoch+"/"+seq+" currentEpoch="+current;
        if(old.size()!=1 ||next.isEmpty() ||((Long)field(old.get(0),"epoch"))!=epoch
                ||((Long)field(old.get(0),"sequence"))!=seq-1 ||((Long)field(next.get(0),"epoch"))<=epoch)
            return "WAIT completePredecessor=false";
        return "EXCLUDED_AFTER_CERTIFIED_PREFIX origin="+epoch+"/"+seq+" acceptedHead="+(seq-1)
                +" nextEpoch="+field(next.get(0),"epoch")+" nextSequence="+field(next.get(0),"sequence")
                +" currentEpoch="+current;
    }
    private static Object field(Object o,String name)throws Exception{
        Field f=o.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(o);
    }
    static final class Window {public long epoch;public List<Frame> frames;Window(long e,Frame...f){epoch=e;frames=java.util.Arrays.asList(f);}}
    static final class Frame {public long epoch,sequence;Frame(long e,long s){epoch=e;sequence=s;}}
    public static void main(String[] ignored)throws Exception{
        if(!classify(new Window(14,new Frame(12,399)),new Window(14,new Frame(13,1)),12,400).startsWith("EXCLUDED_AFTER_CERTIFIED_PREFIX"))throw new AssertionError("Known cut missing");
        if(!classify(new Window(14,new Frame(12,399),new Frame(12,400)),new Window(14,new Frame(12,400)),12,400).startsWith("INCLUDED"))throw new AssertionError("Included command rejected");
        for(Window old:new Window[]{new Window(14),new Window(13,new Frame(12,399))})
            if(!classify(old,new Window(14,new Frame(13,1)),12,400).startsWith("WAIT"))throw new AssertionError("Unknown cut accepted");
        System.out.println("CERTIFIED_ORIGINAL_COORDINATE_READ_OBSERVER_SELF_TEST_PASS");
    }
}
