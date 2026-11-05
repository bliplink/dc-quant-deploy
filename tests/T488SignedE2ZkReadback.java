import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.apache.zookeeper.ZooKeeper;
import org.apache.zookeeper.Watcher;
import org.apache.zookeeper.data.Stat;

/** Read-only independently connected verification: no CAS, no READY issuer. */
public final class T488SignedE2ZkReadback {
    private static final String ROOT="/otc/t488-fresh-20261105-r1";
    public static void main(String[] args)throws Exception {
        if(args.length!=1)throw new IllegalArgumentException("ZK hosts required");
        CountDownLatch connected=new CountDownLatch(1);
        try(ZooKeeper zk=new ZooKeeper(args[0],10000,e->{
            if(e.getState()==Watcher.Event.KeeperState.SyncConnected)connected.countDown();
        })){
            if(!connected.await(15,TimeUnit.SECONDS))
                throw new IllegalStateException("real three-member ZK quorum unreachable");
            for(String svc:new String[]{"order","trade"}){
                String service="order".equals(svc)?"OrderSvr":"TradeSvr";
                Stat version=new Stat();
                byte[] raw=zk.getData(ROOT+"/"+svc+"/manifest",false,version);
                String[] lines=new String(raw,StandardCharsets.UTF_8).split("\\n");
                if(version.getVersion()!=1 || lines.length!=257
                        ||!"NPC1|2".equals(lines[0]))
                    throw new IllegalStateException("signed first E2 READY manifest not exact "+svc);
                int a=0,b=0;
                for(int i=0;i<256;i++){
                    String p=String.format(Locale.ROOT,"P%03d",i);
                    String primary=service+(i<128?"A":"B");
                    String replica=service+(i<128?"B":"A");
                    String expected=p+"|2|"+primary+"|"+replica+"|STRICT_QUORUM|READY";
                    if(!expected.equals(lines[i+1]))
                        throw new IllegalStateException("signed E2 role differs "+svc+" "+p);
                    if(i<128)a++;else b++;
                }
                System.out.println("T488_INDEPENDENT_SIGNED_E2_ZK_READBACK_PASS service="+service
                        +" version="+version.getVersion()+" partitions=256"
                        +" A_PRIMARY="+a+" B_PRIMARY="+b+" READY=256");
            }
        }
    }
}