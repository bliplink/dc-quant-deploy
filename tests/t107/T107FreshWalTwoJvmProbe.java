import com.app.common.replication.*;
import com.app.dc.security.ExistingDemoRsaNodeIdentity;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.file.*;
import java.security.*;
import java.util.*;
import java.util.concurrent.CountDownLatch;

/**
 * Isolated, real TWO-DOCKER-JVM physical certificate transport probe.
 * Uses ONLY original Demo RSA A/B keys via read-only mounts. Does not start
 * Order/Trade business and does not grant real cluster READY or failover.
 */
public final class T107FreshWalTwoJvmProbe {
    private static final String A="CommonHaDemoA",B="CommonHaDemoB";
    private static final String PART="P090",SERVICE="CommonHaDemo";
    private static final long EPOCH=1;
    private static String sha(byte[] bytes)throws Exception {
        byte[] raw=MessageDigest.getInstance("SHA-256").digest(bytes);
        StringBuilder b=new StringBuilder(64);
        for(byte x:raw)b.append(String.format("%02x",x & 255));
        return b.toString();
    }
    private static DurableWalCommitQuorum.Membership membership(
            ExistingDemoRsaNodeIdentity id)throws Exception{
        return new DurableWalCommitQuorum.Membership(SERVICE,PART,A,EPOCH,1,
                Arrays.asList(new DurableWalCommitQuorum.Member(A,"demo-mac-A-jvm",id.publicMembers().get(A)),
                              new DurableWalCommitQuorum.Member(B,"demo-mac-B-jvm",id.publicMembers().get(B))));
    }
    public static void main(String[] args)throws Exception {
        if(args.length!=3 && args.length!=4)
            throw new IllegalArgumentException("server|client, nodeId, address, optional-count");
        boolean server=args[0].equals("server");
        String node=args[1];
        if(!node.equals(server?B:A))throw new IllegalArgumentException("wrong mounted RSA node identity");
        ExistingDemoRsaNodeIdentity id=ExistingDemoRsaNodeIdentity.open(
                Paths.get("/srv/v19/local-identity"),Paths.get("/srv/v19/identities"),node);
        DurableWalCommitQuorum.Membership members=membership(id);
        Path base=Paths.get("/srv/t106-data");
        DurableWalCertificateCustody.Authority trusted=m->{
            if(m!=members && !members.digest.equals(m.digest))
                throw new IllegalStateException("old Common Epoch revoked");
        };
        try(CommonFileBusinessWal wal=new CommonFileBusinessWal(base.resolve("business.wal"),EPOCH);
            DurableWalCertificateCustody custodian=new DurableWalCertificateCustody(
                    base.resolve("custody"),members,wal,trusted)) {
            if(server) {
                ReplicationHandler handler=batch->{
                    try {
                        if(batch.getEpoch()!=EPOCH || !batch.getServiceName().equals(SERVICE)
                                || !batch.getPartitionId().equals(PART) || batch.size()!=1)
                            throw new IllegalStateException("invalid signed physical replica batch");
                        ReplicationRecord frame=batch.getRecords().get(0);
                        return wal.receiveReplicated(batch,members,B,id.privateKey());
                    }catch(Exception failed){
                        return new ReplicationAck(ReplicationStatus.ERROR,PART,EPOCH,0,1,"DENIED");
                    }
                };
                DurableWalCertificateCustodyControlHandler control=
                        new DurableWalCertificateCustodyControlHandler(
                                members,B,id.privateKey(),custodian,trusted);
                try(DirectNettyReplicationServer tcp=new DirectNettyReplicationServer(
                        "0.0.0.0",19591,handler,control)){
                    tcp.start();System.out.println("T107_JVM_B_READY_REAL_NETTY_19591");System.out.flush();
                    new CountDownLatch(1).await();
                }
            }else{
                try(DurableWalCommitIndex index=new DurableWalCommitIndex(
                        base.resolve("commit"),members);
                    DurableWalCustodyReceiptLedger receipts=new DurableWalCustodyReceiptLedger(
                        base.resolve("receipts"),members,custodian);
                    DirectNettyReplicationTransport tcp=new DirectNettyReplicationTransport(3500,65536)){
                    Map<String,ReplicationEndpoint> peers=Collections.singletonMap(
                            B,new ReplicationEndpoint(B,args[2],19591));
                    DirectNettyCertifiedBusinessTransport physical=
                            new DirectNettyCertifiedBusinessTransport(members,A,
                                    id.privateKey(),wal,custodian,trusted,tcp,peers,2800);
                    CertifiedBusinessCommandBoundary boundary=
                            new CertifiedBusinessCommandBoundary(members,index,receipts,
                                    wal,trusted,(p,e)->{
                                        if(!p.equals(PART) || e!=EPOCH)
                                            throw new IllegalStateException("lost Common primary grant");
                                    },physical);
                    int count=args.length==4?Integer.parseInt(args[3]):2;
                    if(count<=0 || count>128)throw new IllegalArgumentException("bounded test count");
                    long[] samples=new long[count];
                    for(int n=1;n<=count;n++){
                        long started=System.nanoTime();
                        DurableWalCommitAckGate.Confirmed ack=boundary.commit(
                                (p,e,seq)->("ORDER_RECORD_"+p+":"+e+":"+seq).getBytes("UTF-8"));
                        if(ack.sequence!=n || !ack.durability.equals("QUORUM_DURABLE"))
                            throw new AssertionError("not certified remote ACK");
                        samples[n-1]=System.nanoTime()-started;
                    }
                    Arrays.sort(samples);
                    System.out.println("T107_ACK_LATENCY_MILLIS count="+count+
                            " p50="+String.format(java.util.Locale.ROOT,"%.3f",samples[(count-1)/2]/1e6)
                            +" p95="+String.format(java.util.Locale.ROOT,"%.3f",samples[(int)Math.ceil(count*.95)-1]/1e6)
                            +" p99="+String.format(java.util.Locale.ROOT,"%.3f",samples[(int)Math.ceil(count*.99)-1]/1e6));
                    if(index.committedSequence()!=count || custodian.highestVerified().committedSequence!=count
                            || receipts.requireRecovered(index.verifiedHighestCertificate()).size()!=2)
                        throw new AssertionError("missing physical two-JVM remote custody proof");
                    System.out.println("T107_TWO_DISTINCT_DOCKER_JVMS_NETTY_RSA_WAL_CUSTODY_PASS seq="+count);
                    System.out.println("ONE_MAC_SHARED_HOST_NOT_INDEPENDENT_PHYSICAL_HA");
                }
            }
        }
    }
}
