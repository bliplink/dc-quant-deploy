import com.app.common.zk.ZookeeperClient;
import com.app.common.replication.*;
import org.apache.zookeeper.CreateMode;
import java.util.LinkedHashMap;
import java.util.Map;

/** Isolated brand-new E1 namespace. Never rewrites old T149 or grants READY. */
public final class T164OriginalFreshNamespace {
    private static final String ROOT="/otc/t164";
    private static void createIfAbsent(ZookeeperClient z,String path)throws Exception{
        if(!z.exists(path))z.create(path,"",CreateMode.PERSISTENT);
    }
    public static void main(String[] args)throws Exception{
        if(args.length!=2 || !("order".equals(args[0])||"trade".equals(args[0])))
            throw new IllegalArgumentException("order|trade and reachable isolated ZK quorum required");
        String kind=args[0],scope=ROOT+"/"+kind;
        String primary="order".equals(kind)?"OrderSvrA":"TradeSvrA";
        String replica="order".equals(kind)?"OrderSvrB":"TradeSvrB";
        Map<String,ZkNodeScopedControlPlane.Assignment> assignments=new LinkedHashMap<>();
        assignments.put("P090",new ZkNodeScopedControlPlane.Assignment(
            new NodePartitionGrantTable.Partition("P090",1,primary,replica,
                DurableWalAckPolicy.STRICT_QUORUM),false));
        String required=new ZkNodeScopedControlPlane.Manifest(1,assignments).encode();
        ZookeeperClient z=new ZookeeperClient(args[1],null,null);
        try{
            createIfAbsent(z,"/otc");createIfAbsent(z,ROOT);
            createIfAbsent(z,scope);createIfAbsent(z,scope+"/leases");
            String path=scope+"/manifest";
            if(!z.exists(path))z.create(path,required,CreateMode.PERSISTENT);
            if(!required.equals(String.valueOf(z.readData(path))))
                throw new IllegalStateException("unexpected pre-existing T164 E1 manifest, refuse overwrite");
            ZkNodeScopedControlPlane.Manifest seen=ZkNodeScopedControlPlane.Manifest.parse(required);
            if(seen.generation!=1 || seen.assignments.size()!=1
                    || seen.assignments.get("P090").ready)
                throw new IllegalStateException("never mint READY or fake primary");
            System.out.println("T164_NEW_ZK_NAMESPACE_E1_RECOVERING_ONLY_PASS "
                    +scope+" voterA="+primary+" voterB="+replica+" ready=false");
        }finally{z.close();}
    }
}