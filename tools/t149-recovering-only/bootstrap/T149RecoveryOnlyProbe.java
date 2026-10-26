import com.app.common.zk.ZookeeperClient;
import com.app.common.replication.*;
import org.apache.zookeeper.data.Stat;
import java.util.Collections;
import java.util.concurrent.TimeUnit;

/** Real TCP business denial + unsigned-control denial and current
 * independently owned ZK ephemeral lease in each original candidate JVM. */
public final class T149RecoveryOnlyProbe {
    public static void main(String[] args)throws Exception{
        if(args.length!=7)throw new IllegalArgumentException("service,node,partition,port,manifest,lease,zk");
        String service=args[0],node=args[1],partition=args[2];
        int port=Integer.parseInt(args[3]);
        ZookeeperClient zk=new ZookeeperClient(args[6],null,null);
        try {
            Stat leaseStat=new Stat();Object lease=zk.readData(args[5],leaseStat);
            if(lease==null || leaseStat.getEphemeralOwner()<=0)
                throw new IllegalStateException("Common lease missing REAL ZK ephemeral session: "+node);
            ZkNodeScopedControlPlane.Manifest manifest=ZkNodeScopedControlPlane.Manifest.parse(
                    String.valueOf(zk.readData(args[4])));
            ZkNodeScopedControlPlane.Assignment assignment=manifest.assignments.get(partition);
            if(assignment==null || assignment.ready || assignment.partition.epoch!=1
                || (!node.equals(assignment.partition.primary)
                    && !node.equals(assignment.partition.replica)))
                throw new IllegalStateException("invalid Common non-ready assignment");
            try(DirectNettyReplicationTransport tcp=new DirectNettyReplicationTransport(3000,65536)){
                ReplicationEndpoint to=new ReplicationEndpoint(node,"127.0.0.1",port);
                ReplicationBatch request=new ReplicationBatch(service,partition,1,
                    Collections.singletonList(new ReplicationRecord(1,"STATE_NEW","T149_DENIED",
                            System.currentTimeMillis(),new byte[]{1,2,3})));
                ReplicationAck ack=tcp.replicate(to,request).get(5,TimeUnit.SECONDS);
                if(ack==null || ack.isSuccess() ||
                        !ack.getMessage().contains("COMMON_RECOVERING_BUSINESS_WAL_FORBIDDEN"))
                    throw new IllegalStateException("RECOVERING improperly accepted business WAL: "+ack);
                ReplicationControlResponse cmd=tcp.control(to,
                    new ReplicationControlRequest(service,"WAL_COMMIT",partition,new byte[0]))
                        .get(5,TimeUnit.SECONDS);
                if(cmd==null || cmd.isSuccess() ||
                        !"COMMON_RECOVERING_DENIED".equals(cmd.getCode()))
                    throw new IllegalStateException("RECOVERING allowed unsigned external commit");
            }
            System.out.println("T149_REAL_NODE_ZK_EPHEMERAL_LEASE_TCP_DENY_PASS service="+service+
                " node="+node+" partition="+partition+" epoch=1 ready=false"+
                " businessWal=DENIED unsignedCommit=DENIED sessionOwner=VALID");
        }finally{zk.close();}
    }
}
