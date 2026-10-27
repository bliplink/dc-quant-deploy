import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Locale;

/**
 * Read-only, service-JAR-bound 256-shard canonical empty-business-image check.
 * No keys, WAL, signature, Genesis seal, ZK update or READY side effects.
 * Exact original local business state still requires independent Common
 * FencedRegisteredBusinessDomain verification before a real E1 install.
 */
public final class CommonDemoE1ImageCensus {
    private static String hex(byte[] digest){
        StringBuilder out=new StringBuilder(digest.length*2);
        for(byte b:digest)out.append(String.format("%02x",b&0xff));
        return out.toString();
    }
    public static void main(String[] args)throws Exception{
        if(args.length!=1 ||
                !("OrderSvr".equals(args[0])||"TradeSvr".equals(args[0])))
            throw new IllegalArgumentException("OrderSvr|TradeSvr");
        Class<?> helper=Class.forName("CommonDemoOriginalE1Birth");
        Method image=helper.getDeclaredMethod("freshDomainImage",
                String.class,String.class);
        image.setAccessible(true);
        MessageDigest cumulative=MessageDigest.getInstance("SHA-256");
        int min=Integer.MAX_VALUE,max=0,total=0;
        for(int i=0;i<256;i++){
            String part=String.format(Locale.ROOT,"P%03d",i);
            byte[] bytes=(byte[])image.invoke(null,args[0],part);
            min=Math.min(min,bytes.length);
            max=Math.max(max,bytes.length);
            total+=bytes.length;
            cumulative.update(part.getBytes(StandardCharsets.UTF_8));
            cumulative.update((byte)0);
            cumulative.update(MessageDigest.getInstance("SHA-256").digest(bytes));
        }
        System.out.println("COMMON_DEMO_E1_CANONICAL_IMAGE_CENSUS service="+args[0]
            +" partitions=256 minBytes="+min+" maxBytes="+max+" totalBytes="+total
            +" combinedSha256="+hex(cumulative.digest())
            +" diskWriters=0 ready=false");
    }
}
