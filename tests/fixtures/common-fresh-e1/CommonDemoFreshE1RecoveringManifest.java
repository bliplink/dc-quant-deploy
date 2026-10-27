import com.app.common.replication.*;
import com.app.common.zk.ZookeeperClient;
import org.apache.zookeeper.CreateMode;
import java.util.*;

public final class CommonDemoFreshE1RecoveringManifest {
  private static String ROOT="/otc/demo-real-common";
  private static void ensure(ZookeeperClient zk,String p)throws Exception {
    if(!zk.exists(p)) zk.create(p,"",CreateMode.PERSISTENT);
  }
  private static String manifest(String service)throws Exception{
    final String n="order".equals(service)?"OrderSvr":"TradeSvr";
    Map<String,ZkNodeScopedControlPlane.Assignment> parts=new LinkedHashMap<>();
    for(int i=0;i<256;i++){
      String id=String.format(Locale.ROOT,"P%03d",i);
      String a=n+((i%2)==0?"A":"B"),b=n+((i%2)==0?"B":"A");
      parts.put(id,new ZkNodeScopedControlPlane.Assignment(
        new NodePartitionGrantTable.Partition(id,1,a,b,DurableWalAckPolicy.STRICT_QUORUM),false));
    }
    ZkNodeScopedControlPlane.Manifest out=new ZkNodeScopedControlPlane.Manifest(1,parts);
    String encoded=out.encode();
    ZkNodeScopedControlPlane.Manifest checked=ZkNodeScopedControlPlane.Manifest.parse(encoded);
    if(checked.generation!=1 || checked.assignments.size()!=256)
      throw new IllegalStateException("Invalid 256 partition genesis census");
    for(ZkNodeScopedControlPlane.Assignment p:checked.assignments.values()){
      if(p.ready || p.partition.epoch!=1 ||
        p.partition.policy!=DurableWalAckPolicy.STRICT_QUORUM)
        throw new IllegalStateException("Unsafe initial E1 assignment");
    }
    return encoded;
  }
  public static void main(String[] args)throws Exception{
    if(args.length!=2 || (!"--dry-run".equals(args[0]) && !"--apply".equals(args[0])))
      throw new IllegalArgumentException("--dry-run|--apply ZK_HOSTS");
    String specified=System.getProperty("otc.fresh.root",ROOT);
    if(!specified.matches("/otc/[A-Za-z0-9_-]{4,64}"))
      throw new IllegalArgumentException("explicit new Common Demo namespace required");
    ROOT=specified;
    String order=manifest("order"),trade=manifest("trade");
    if("--dry-run".equals(args[0])){
      System.out.println("COMMON_DEMO_FRESH_E1_PLAN partitions=256 per_service strictRF2=true ready=false");
      return;
    }
    ZookeeperClient zk=new ZookeeperClient(args[1],null,null);
    try{
      ensure(zk,"/otc"); ensure(zk,ROOT);
      for(String svc:new String[]{"order","trade"}){
        String ns=ROOT+"/"+svc;
        ensure(zk,ns);ensure(zk,ns+"/leases");
        String p=ns+"/manifest",content="order".equals(svc)?order:trade;
        if(!zk.exists(p))zk.create(p,content,CreateMode.PERSISTENT);
        if(!content.equals(String.valueOf(zk.readData(p))))
          throw new IllegalStateException("Existing manifest differs; never overwrite "+svc);
        System.out.println("COMMON_DEMO_FRESH_E1_MANIFEST_PASS service="+svc+
          " partitions=256 ready=false signed_genesis=false");
      }
    }finally{zk.close();}
  }
}
