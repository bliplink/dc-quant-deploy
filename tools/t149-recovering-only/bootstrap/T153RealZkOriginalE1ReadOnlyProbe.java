import com.app.common.zk.ZookeeperClient;
import com.app.common.replication.*;
import org.apache.zookeeper.data.Stat;
import java.nio.file.*;
import java.security.*;
import java.security.spec.*;
import java.util.*;

/** Isolated T153 READ-ONLY live ZK and original signed Genesis census probe.
 * Not a zero-WAL physical audit; not READY; does not CAS or touch manifest.
 * Runs ONLY in pre-existing T149 candidate containers, never Demo/formal.
 */
public final class T153RealZkOriginalE1ReadOnlyProbe {
    private static final String RSA="/read-only-original-rsa";
    private static String keyAlias(String node){
        if(node.endsWith("A"))return "CommonHaDemoA";
        if(node.endsWith("B"))return "CommonHaDemoB";
        if(node.endsWith("C"))return "CommonHaDemoC";
        throw new IllegalArgumentException("unexpected original pinned RSA node");
    }
    private static PublicKey pinned(String node)throws Exception{
        byte[] bytes=Files.readAllBytes(Paths.get(RSA,"public",keyAlias(node)+".pub.der"));
        return KeyFactory.getInstance("RSA").generatePublic(new X509EncodedKeySpec(bytes));
    }
    private static DurableWalCommitQuorum.Membership census(String svc,String p,
            String first,String second)throws Exception{
        return new DurableWalCommitQuorum.Membership(svc,p,first,1,1,Arrays.asList(
            new DurableWalCommitQuorum.Member(first,"t150-isolated-volume-"+first,pinned(first)),
            new DurableWalCommitQuorum.Member(second,"t150-isolated-volume-"+second,pinned(second))));
    }
    private static void verify(String svc,String partition,
            String primary,String replica,String local)throws Exception{
        if(!Arrays.asList("OrderSvr","TradeSvr").contains(svc)
                || !partition.matches("P[0-9]{3}")
                || !local.equals(primary)&&!local.equals(replica))
            throw new IllegalArgumentException("T153 unknown node or partition");
        String namespace="/otc/t149/"+("OrderSvr".equals(svc)?"order":"trade");
        DurableWalCommitQuorum.Membership m=census(svc,partition,primary,replica);
        String base="/srv/dc/data/t150-original-genesis/"+partition;
        CommonCertifiedGenesisQuorum.Verified signed=CommonCertifiedGenesisQuorum.reopen(
            Paths.get(base,"sealed"),m);
        CommonDurableGenesisVoterImage voter=new CommonDurableGenesisVoterImage(
            Paths.get(base,"node-voter"),m,local);
        if(!MessageDigest.isEqual(signed.originalImage(),voter.readCertifiedLocalImage()))
            throw new IllegalStateException("local fsynced original business Genesis differs");
        ZookeeperClient zk=new ZookeeperClient("zk1:2181,zk2:2181,zk3:2181",null,null);
        try{
            String manifestPath=namespace+"/manifest";
            Stat ms=new Stat();
            String raw=String.valueOf(zk.readData(manifestPath,ms));
            ZkNodeScopedControlPlane.Manifest published=
                ZkNodeScopedControlPlane.Manifest.parse(raw);
            ZkNodeScopedControlPlane.Assignment assignment=published.assignments.get(partition);
            if(published.generation!=m.configurationVersion || assignment==null
                    || assignment.ready || assignment.partition.epoch!=1
                    || assignment.partition.policy!=DurableWalAckPolicy.STRICT_QUORUM
                    || !primary.equals(assignment.partition.primary)
                    || !replica.equals(assignment.partition.replica))
                throw new IllegalStateException("original E1 ZK RECOVERING census not authentic");
            long[] sessions=new long[2];
            String[] tokens=new String[2];
            String[] nodes={primary,replica};
            for(int i=0;i<2;i++){
                Stat vote=new Stat();
                Object v=zk.readData(namespace+"/leases/"+nodes[i],vote);
                if(v==null || vote.getEphemeralOwner()<=0)
                    throw new IllegalStateException("original RF2 voter lease absent");
                sessions[i]=vote.getEphemeralOwner();tokens[i]=String.valueOf(v);
            }
            if(sessions[0]==sessions[1])
                throw new IllegalStateException("two original voters share ZK session");
            Stat updated=new Stat();
            Object again=zk.readData(manifestPath,updated);
            if(updated.getVersion()!=ms.getVersion() || !raw.equals(String.valueOf(again)))
                throw new IllegalStateException("Common manifest changed during physical certificate inspect");
            for(int i=0;i<2;i++){
                Stat lease=new Stat();
                Object current=zk.readData(namespace+"/leases/"+nodes[i],lease);
                if(lease.getEphemeralOwner()!=sessions[i]
                        || !tokens[i].equals(String.valueOf(current)))
                    throw new IllegalStateException("Common original voter lease retired during verification");
            }
            System.out.println("T153_READONLY_REAL_ZK_RF2_ORIGINAL_RSA_GENESIS_PASS "
                +"service="+svc+" partition="+partition+" local="+local
                +" voters=2 sessions=distinct epoch=1 recovering=true sha="+signed.originalSha256);
            System.out.println("T153_NO_READY_NO_WAL_ATTESTATION: observer has no CAS ownership, physical WAL zero audit or business state proof");
        }finally{zk.close();}
    }
    public static void main(String[] args)throws Exception{
        if(args.length!=5)throw new IllegalArgumentException(
                "service partition originalPrimary originalReplica originalLocal");
        verify(args[0],args[1],args[2],args[3],args[4]);
    }
}