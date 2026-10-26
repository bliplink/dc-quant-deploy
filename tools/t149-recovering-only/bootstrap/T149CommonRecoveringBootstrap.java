import com.app.common.zk.ZookeeperClient;
import com.app.common.replication.*;
import org.apache.zookeeper.CreateMode;
import java.util.LinkedHashMap;
import java.util.Map;

/** Initial, non-READY ZK assignment only, encoded by the EXACT Common
 * ZkNodeScopedControlPlane.Manifest. NEVER issues Genesis, grant, or READY.
 * Must be followed by real signed Genesis & business replay before trading. */
public final class T149CommonRecoveringBootstrap {
    private static final String ROOT="/otc/t149";
    private static void ensure(ZookeeperClient client,String path)throws Exception{
        if(!client.exists(path))client.create(path,"",CreateMode.PERSISTENT);
    }
    private static void partition(Map<String,ZkNodeScopedControlPlane.Assignment> into,
            String id,String primary,String replica){
        into.put(id,new ZkNodeScopedControlPlane.Assignment(
                new NodePartitionGrantTable.Partition(id,1,primary,replica,
                        DurableWalAckPolicy.STRICT_QUORUM),false));
    }
    public static void main(String[] args)throws Exception{
        if(args.length!=2 || !("order".equals(args[0]) || "trade".equals(args[0])))
                throw new IllegalArgumentException("Use order|trade and internal ZK connect string");
        final String service=args[0];
        final String scope=ROOT+"/"+service;
        final Map<String,ZkNodeScopedControlPlane.Assignment> assignment=new LinkedHashMap<>();
        if("order".equals(service)){
            partition(assignment,"P090","OrderSvrA","OrderSvrB");
            partition(assignment,"P091","OrderSvrC","OrderSvrB");
        }else partition(assignment,"P090","TradeSvrA","TradeSvrB");
        final String candidate=new ZkNodeScopedControlPlane.Manifest(1,assignment).encode();
        if(candidate.contains("READY\n") || candidate.endsWith("|READY"))
            throw new IllegalStateException("cannot initialize a trading READY from installer");
        ZookeeperClient zk=new ZookeeperClient(args[1],null,null);
        try{
            ensure(zk,"/otc");ensure(zk,ROOT);ensure(zk,scope);ensure(zk,scope+"/leases");
            String manifest=scope+"/manifest";
            if(!zk.exists(manifest))zk.create(manifest,candidate,CreateMode.PERSISTENT);
            Object actual=zk.readData(manifest);
            if(!candidate.equals(String.valueOf(actual)))
                throw new IllegalStateException("existing Common manifest not equal; NO REWRITE");
            ZkNodeScopedControlPlane.Manifest parsed=ZkNodeScopedControlPlane.Manifest.parse(candidate);
            for(ZkNodeScopedControlPlane.Assignment a:parsed.assignments.values())
                if(a.ready || a.partition.epoch!=1 ||
                        a.partition.policy!=DurableWalAckPolicy.STRICT_QUORUM)
                    throw new IllegalStateException("never publish READY or uncertified ACK");
            System.out.println("T149_COMMON_INITIAL_ZK_RECOVERING_ONLY="+service+
                    " shards="+parsed.assignments.size()+" generation="+parsed.generation+
                    " businessReady=false certifiedGenesis=false");
        }finally{zk.close();}
    }
}
