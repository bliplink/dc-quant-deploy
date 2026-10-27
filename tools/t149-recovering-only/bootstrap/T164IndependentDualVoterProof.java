import com.app.common.replication.*;
import com.app.common.zk.ZookeeperClient;
import org.apache.zookeeper.data.Stat;
import java.nio.file.*;
import java.security.*;
import java.security.spec.*;
import java.util.*;

/** Independent read-only process (not the local recovery lease holder)
 * verifies BOTH real original RSA birth WAL roots, BOTH durable REPLAY_COMPLETE
 * ledgers, immutable original signed Genesis, and current original ZK RF2
 * RECOVERING two distinct sessions. Cannot grant READY. */
public final class T164IndependentDualVoterProof {
    private static PublicKey voter(String node)throws Exception{
        String alias=node.endsWith("A")?"CommonHaDemoA":
                node.endsWith("B")?"CommonHaDemoB":null;
        if(alias==null)throw new IllegalArgumentException("unknown voter");
        Path file=Paths.get("/rsa-public",alias+".pub.der");
        return KeyFactory.getInstance("RSA").generatePublic(
            new X509EncodedKeySpec(Files.readAllBytes(file)));
    }
    private static void ledger(String physicalNode,
            String exactSha,String dir)throws Exception{
        DurableRecoveryInstallLedger.Entry e=new DurableRecoveryInstallLedger(
            Paths.get(dir,"t164-e1-install","P090","ledger")).read("P090");
        if(e==null || e.phase!=DurableRecoveryInstallLedger.Phase.REPLAY_COMPLETE
                || !e.partitionId.equals("P090")
                || e.epoch!=1 || e.snapshotSeq!=0
                || e.committedHeadEpoch!=1 || e.committedHeadSeq!=0
                || e.replaySeq!=0 || e.sourceStateSeq!=0
                || e.baselineStateSeq!=0 || e.sourceStateEpoch!=1
                || !e.sha256.equals(exactSha))
            throw new IllegalStateException("Untrusted exact durable E1 replay ledger for "+physicalNode);
    }
    private static void verify(String svc,String kind,String primary,String replica)
            throws Exception{
        String originalNs="/otc/t164/"+kind;
        DurableWalCommitQuorum.Membership m=new DurableWalCommitQuorum.Membership(
            svc,"P090",primary,1,1,Arrays.asList(
                new DurableWalCommitQuorum.Member(primary,
                    "t150-isolated-volume-"+primary,voter(primary)),
                new DurableWalCommitQuorum.Member(replica,
                    "t150-isolated-volume-"+replica,voter(replica))));
        Path nodeA=Paths.get("/voters","a");
        Path nodeB=Paths.get("/voters","b");
        CommonCertifiedGenesisQuorum.Verified signed=
            CommonCertifiedGenesisQuorum.reopen(
                nodeA.resolve("t150-original-genesis/P090/sealed"),m);
        CommonCertifiedGenesisQuorum.Verified second=
            CommonCertifiedGenesisQuorum.reopen(
                nodeB.resolve("t150-original-genesis/P090/sealed"),m);
        if(!signed.originalSha256.equals(second.originalSha256))
            throw new IllegalStateException("different original signed Genesis versions");
        Map<String,Path> roots=new LinkedHashMap<>();
        roots.put(primary,nodeA.resolve("t164-original-wal/P090"));
        roots.put(replica,nodeB.resolve("t164-original-wal/P090"));
        CommonOriginalE1ZeroAckBirthEvidence physical=
            new CommonOriginalE1ZeroAckBirthEvidence(originalNs,signed.originalSha256,roots);
        for(DurableWalCommitQuorum.Member member:m.members.values())
            physical.requireOriginalPhysicalZeroAckWal(m,member);
        ledger(primary,signed.originalSha256,nodeA.toString());
        ledger(replica,signed.originalSha256,nodeB.toString());
        ZookeeperClient zk=new ZookeeperClient("zk1:2181,zk2:2181,zk3:2181",null,null);
        try{
            String manifest=originalNs+"/manifest";
            Stat before=new Stat();
            String raw=String.valueOf(zk.readData(manifest,before));
            ZkNodeScopedControlPlane.Manifest live=ZkNodeScopedControlPlane.Manifest.parse(raw);
            ZkNodeScopedControlPlane.Assignment p=live.assignments.get("P090");
            if(live.generation!=1 || live.assignments.size()!=1
                    || p==null || p.ready || p.partition.epoch!=1
                    || !primary.equals(p.partition.primary)
                    || !replica.equals(p.partition.replica)
                    || p.partition.policy!=DurableWalAckPolicy.STRICT_QUORUM)
                throw new IllegalStateException("original E1 ZK manifest changed or READY");
            long[] sessions=new long[2];
            String[] nodes={primary,replica};
            for(int i=0;i<2;i++){
                Stat st=new Stat();
                zk.readData(originalNs+"/leases/"+nodes[i],st);
                sessions[i]=st.getEphemeralOwner();
                if(sessions[i]<=0)throw new IllegalStateException("original voter session missing "+nodes[i]);
            }
            if(sessions[0]==sessions[1])
                throw new IllegalStateException("RF2 original voters share a single ZK lease");
            Stat after=new Stat();
            String reread=String.valueOf(zk.readData(manifest,after));
            if(before.getVersion()!=after.getVersion() || !raw.equals(reread))
                throw new IllegalStateException("manifest changed during independent proof");
            System.out.println("T164_INDEPENDENT_REAL_RF2_GENESIS_BIRTH_REPLAY_ZK_PASS service="
                +svc+" partition=P090 originalSessions=distinct"
                +" epoch=1 head=0 replay=0 signedSha256="+signed.originalSha256
                +" ready=false");
        }finally{zk.close();}
    }
    public static void main(String[] a)throws Exception{
        if(a.length!=1)throw new IllegalArgumentException("order|trade");
        if("order".equals(a[0]))verify("OrderSvr","order","OrderSvrA","OrderSvrB");
        else if("trade".equals(a[0]))verify("TradeSvr","trade","TradeSvrA","TradeSvrB");
        else throw new IllegalArgumentException("unknown service");
    }
}