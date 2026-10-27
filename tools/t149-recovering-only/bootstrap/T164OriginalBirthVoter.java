import com.app.common.replication.*;
import java.nio.file.*;
import java.security.*;
import java.security.spec.*;
import java.util.*;

/** One original physical voter's irreversible birth-time RSA zero-ACK proof.
 * Runs ONLY for a new T164 test namespace with a never-existing writer dir.
 * Never touches T149/T150 signed Genesis or official Demo.
 */
public final class T164OriginalBirthVoter {
    static final String RSA="/read-only-original-rsa";
    private static String alias(String n){
        if(n.endsWith("A"))return "CommonHaDemoA";
        if(n.endsWith("B"))return "CommonHaDemoB";
        throw new IllegalArgumentException("only original RF2 A/B keys can sign T164");
    }
    private static PublicKey pinned(String n)throws Exception {
        return KeyFactory.getInstance("RSA").generatePublic(new X509EncodedKeySpec(
            Files.readAllBytes(Paths.get(RSA,"public",alias(n)+".pub.der"))));
    }
    private static PrivateKey mine(String n)throws Exception {
        return KeyFactory.getInstance("RSA").generatePrivate(new PKCS8EncodedKeySpec(
            Files.readAllBytes(Paths.get(RSA,n.endsWith("A")?"a":"b","node.pk8"))));
    }
    public static void main(String[] args)throws Exception {
        if(args.length!=5)throw new IllegalArgumentException(
            "OrderSvr|TradeSvr P090 primary replica signer");
        String svc=args[0],part=args[1],primary=args[2],replica=args[3],node=args[4];
        String kind="OrderSvr".equals(svc)?"order":"TradeSvr".equals(svc)?"trade":null;
        if(kind==null || !"P090".equals(part)
                || !(node.equals(primary)||node.equals(replica))
                || !primary.endsWith("A") || !replica.endsWith("B"))
            throw new IllegalArgumentException("not a new isolated original E1 RF2 voter");
        DurableWalCommitQuorum.Membership m=new DurableWalCommitQuorum.Membership(
            svc,part,primary,1,1,Arrays.asList(
            new DurableWalCommitQuorum.Member(primary,
                "t150-isolated-volume-"+primary,pinned(primary)),
            new DurableWalCommitQuorum.Member(replica,
                "t150-isolated-volume-"+replica,pinned(replica))));
        Path genesis=Paths.get("/srv/dc/data/t150-original-genesis",part);
        CommonCertifiedGenesisQuorum.Verified signed=
            CommonCertifiedGenesisQuorum.reopen(genesis.resolve("sealed"),m);
        CommonDurableGenesisVoterImage own=new CommonDurableGenesisVoterImage(
            genesis.resolve("node-voter"),m,node);
        if(!signed.originalSha256.equals(SnapshotTransferIntegrity.sha256(
                own.readCertifiedLocalImage())))
            throw new IllegalStateException("original fsynced RSA Genesis not preserved");
        String namespace="/otc/t164/"+kind;
        Path virgin=Paths.get("/srv/dc/data/t164-original-wal",part);
        CommonOriginalE1ZeroAckBirthEvidence.sealVirginRoot(
            virgin,m,node,namespace,own,mine(node));
        Map<String,Path> roots=new LinkedHashMap<>();
        // Both mounts are independently supplied at runtime; this signer
        // must verify only its OWN original filesystem, not claim host HA.
        Path ownRoot=virgin;
        roots.put(primary,node.equals(primary)?ownRoot:Paths.get("/not-mounted-primary"));
        roots.put(replica,node.equals(replica)?ownRoot:Paths.get("/not-mounted-replica"));
        CommonOriginalE1ZeroAckBirthEvidence verifier=
            new CommonOriginalE1ZeroAckBirthEvidence(namespace,signed.originalSha256,roots);
        verifier.requireOriginalPhysicalZeroAckWal(m,m.members.get(node));
        System.out.println("T164_REAL_ORIGINAL_RSA_BIRTH_ZERO_ACK_PASS service="+svc
            +" voter="+node+" partition="+part+" namespace="+namespace
            +" ready=false");
    }
}