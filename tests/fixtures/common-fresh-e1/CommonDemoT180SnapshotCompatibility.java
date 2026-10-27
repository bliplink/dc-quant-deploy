import java.lang.reflect.Method;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.Locale;
/** Tests actual Order/Trade production first-boot DTO against earlier
 * immutable T150 first-boot witness, all 256 shards; never writes evidence. */
public final class CommonDemoT180SnapshotCompatibility {
    public static void main(String[] args)throws Exception {
        if(args.length!=1 || !("Order".equals(args[0])||"Trade".equals(args[0])))
            throw new IllegalArgumentException("Order or Trade");
        String name=args[0];
        Class<?> producer=Class.forName(
                "com.app.dc.service.state."+name+"CommonOriginalE1BirthWiring");
        Method fresh=producer.getMethod("canonicalEmptySnapshot",String.class);
        Method historical=Class.forName("CommonDemoOriginalE1Birth")
                .getDeclaredMethod("freshDomainImage",String.class,String.class);
        historical.setAccessible(true);
        MessageDigest all=MessageDigest.getInstance("SHA-256");
        for(int n=0;n<256;n++){
            String p=String.format(Locale.ROOT,"P%03d",n);
            byte[] produced=(byte[])fresh.invoke(null,p);
            byte[] expected=(byte[])historical.invoke(null,name+"Svr",p);
            if(!Arrays.equals(produced,expected))
                throw new IllegalStateException(name+" Common actual DTO differs from historical E1 at "+p);
            all.update(produced);
        }
        System.out.println(name+" ORIGINAL_COMMON_256_CANONICAL_SNAPSHOT_COMPATIBILITY_PASS");
    }
}
