import com.app.common.replication.CommonCertifiedE2ReplicaHistory;
import com.app.common.replication.DurableWalCommitQuorum;
import java.nio.file.*;
import java.security.*;
import java.security.spec.*;
import java.util.*;

/** T199/T199b real Demo A/B original RSA, custody and complete current
 * physically forced WAL quorum verification. Read-only; does not sign,
 * acquire primary, emit customer ACK, reset data or grant a READY state. */
public final class T199ReadOnlyLiveWalQuorumProof {
    static PublicKey key(Path dir,String alias)throws Exception{
        return KeyFactory.getInstance("RSA").generatePublic(
                new X509EncodedKeySpec(Files.readAllBytes(dir.resolve(alias+".pub.der"))));
    }
    static void check(Path root,Path pubs,String service,String part,String primary,
                      int minExpected)throws Exception {
        DurableWalCommitQuorum.Membership membership =
                new DurableWalCommitQuorum.Membership(service,part,primary,2,2,Arrays.asList(
                        new DurableWalCommitQuorum.Member(service+"A","MacDockerSlotA",key(pubs,"CommonHaDemoA")),
                        new DurableWalCommitQuorum.Member(service+"B","MacDockerSlotB",key(pubs,"CommonHaDemoB"))));
        CommonCertifiedE2ReplicaHistory.Verified a = CommonCertifiedE2ReplicaHistory.openExistingReadOnly(
                root.resolve(service+"A").resolve(service).resolve(service+"A")
                .resolve(part).resolve("epoch-2"),membership,service+"A",4096,64L*1024*1024);
        CommonCertifiedE2ReplicaHistory.Verified b = CommonCertifiedE2ReplicaHistory.openExistingReadOnly(
                root.resolve(service+"B").resolve(service).resolve(service+"B")
                .resolve(part).resolve("epoch-2"),membership,service+"B",4096,64L*1024*1024);
        if(a.authorizesReady() ||b.authorizesReady()
                ||a.committedSequence<minExpected
                ||a.committedSequence!=b.committedSequence
                ||!a.sha256.equals(b.sha256)
                ||a.frames.size()!=a.committedSequence
                ||b.frames.size()!=b.committedSequence)
            throw new AssertionError("signed A/B latest physical committed history divergent");
        for(int i=0;i<a.frames.size();i++){
            CommonCertifiedE2ReplicaHistory.Frame left=a.frames.get(i),right=b.frames.get(i);
            if(left.epoch!=2 ||right.epoch!=2
                    ||left.sequence!=i+1 ||right.sequence!=i+1
                    ||!Arrays.equals(left.payload(),right.payload()))
                throw new AssertionError("Common original signed A/B frame bytes differ");
        }
        System.out.println("T199_LIVE_SIGNED_WAL_QUORUM_PASS service="+service
            +" partition="+part+" committedFrames="+a.committedSequence
            +" AB_original_bytes_identical=true RSA_2of2=true"
            +" readyAuthority=false SHA256="+a.sha256);
    }
    public static void main(String[] args)throws Exception{
        if(args.length!=2)throw new IllegalArgumentException("Demo physical root and pinned original public RSA root");
        Path root=Paths.get(args[0]),pub=Paths.get(args[1]);
        check(root.resolve("OrderSvr"),pub,"OrderSvr","P089","OrderSvrB",664);
        check(root.resolve("TradeSvr"),pub,"TradeSvr","P246","TradeSvrA",7);
    }
}
