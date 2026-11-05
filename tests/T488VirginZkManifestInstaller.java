import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import org.apache.zookeeper.*;
import org.apache.zookeeper.data.Stat;

/** Installs ONLY a new, never-before-used T488 Common E1 RECOVERING namespace.
 * No READY, signer, leader, WAL, ACK or business writes. */
public final class T488VirginZkManifestInstaller {
  private static final String ROOT="/otc/t488-fresh-20261105-r1";
  private static byte[] manifest(Path file,String service)throws Exception {
    byte[] data=Files.readAllBytes(file);
    if(data.length<13000||data.length>16000)
      throw new IllegalStateException("T488 unexpected E1 manifest size");
    String[] lines=new String(data,StandardCharsets.UTF_8).split("\\n");
    if(lines.length!=257||!"NPC1|1".equals(lines[0]))
      throw new IllegalStateException("T488 manifest must contain 256 virgin E1 rows");
    for(int i=0;i<256;i++){
      String p=String.format(Locale.ROOT,"P%03d",i);
      String a=service+"A",b=service+"B";
      String expected=p+"|1|"+(i<128?a:b)+"|"+(i<128?b:a)
          +"|STRICT_QUORUM|RECOVERING";
      if(!expected.equals(lines[i+1]))
        throw new IllegalStateException("T488 unexpected placement "+p);
    }
    return data;
  }
  public static void main(String[] args)throws Exception {
    if(args.length!=3)throw new IllegalArgumentException("host:port orderManifest tradeManifest required");
    final byte[] order=manifest(Paths.get(args[1]),"OrderSvr");
    final byte[] trade=manifest(Paths.get(args[2]),"TradeSvr");
    CountDownLatch connected=new CountDownLatch(1);
    ZooKeeper zk=new ZooKeeper(args[0],10000,event->{
      if(event.getState()==Watcher.Event.KeeperState.SyncConnected)connected.countDown();
    });
    try {
      if(!connected.await(15,TimeUnit.SECONDS))
        throw new IllegalStateException("T488 ZK physical quorum unavailable");
      if(zk.exists(ROOT,false)!=null)
        throw new IllegalStateException("T488 namespace already exists, no reuse");
      if(zk.exists("/otc",false)==null)
        throw new IllegalStateException("original /otc parent absent");
      zk.create(ROOT,new byte[0],ZooDefs.Ids.OPEN_ACL_UNSAFE,CreateMode.PERSISTENT);
      for(String svc:new String[]{"order","trade"}){
        zk.create(ROOT+"/"+svc,new byte[0],ZooDefs.Ids.OPEN_ACL_UNSAFE,CreateMode.PERSISTENT);
        zk.create(ROOT+"/"+svc+"/leases",new byte[0],ZooDefs.Ids.OPEN_ACL_UNSAFE,CreateMode.PERSISTENT);
        zk.create(ROOT+"/"+svc+"/manifest","order".equals(svc)?order:trade,
            ZooDefs.Ids.OPEN_ACL_UNSAFE,CreateMode.PERSISTENT);
      }
      for(String svc:new String[]{"order","trade"}){
        Stat stat=new Stat();
        byte[] actual=zk.getData(ROOT+"/"+svc+"/manifest",false,stat);
        if(stat.getVersion()!=0||!Arrays.equals(actual,"order".equals(svc)?order:trade))
          throw new IllegalStateException("T488 original E1 ZK readback differs");
        System.out.println("T488_NEW_E1_ZK_MANIFEST_PASS service="+svc+
            " version="+stat.getVersion()+" partitions=256 READY=0 "+
            " namespace="+ROOT+"/"+svc+" originalZxid="+stat.getCzxid());
      }
    }finally{zk.close();}
  }
}