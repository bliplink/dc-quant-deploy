import com.app.common.replication.*;
import java.nio.file.*;
import java.security.*;
import java.security.spec.*;
import java.util.*;
public final class T190ReadOnlyWalProof {
    static PublicKey rsa(Path base,String id)throws Exception {
        return KeyFactory.getInstance("RSA").generatePublic(
           new X509EncodedKeySpec(Files.readAllBytes(base.resolve(id+".pub.der"))));
    }
    public static void main(String[] argv)throws Exception {
        if(argv.length!=3)throw new IllegalArgumentException("read-only wal-dir pub-dir partition");
        Path dir=Paths.get(argv[0]), pubs=Paths.get(argv[1]);
        String partition=argv[2];
        if(!partition.matches("P[0-9]{3}"))throw new IllegalArgumentException("verified partition required");
        PublicKey ka=rsa(pubs,"CommonHaDemoA"),kb=rsa(pubs,"CommonHaDemoB");
        List<DurableWalCommitQuorum.Member> peers=Arrays.asList(
            new DurableWalCommitQuorum.Member("TradeSvrA","MacDockerSlotA",ka),
            new DurableWalCommitQuorum.Member("TradeSvrB","MacDockerSlotB",kb));
        String primary=(Integer.parseInt(partition.substring(1))%2)==0?"TradeSvrA":"TradeSvrB";
        Exception failure=null;
        for(int config=1;config<=3;config++){
            try {
                DurableWalCommitQuorum.Membership members=new DurableWalCommitQuorum.Membership(
                    "TradeSvr",partition,primary,2,config,peers);
                try(CommonFileBusinessWal wal=CommonFileBusinessWal.openExistingReadOnly(
                        dir.resolve("business.wal"),2);
                    DurableWalCertificateCustody custody=
                        DurableWalCertificateCustody.openExistingReadOnly(
                            dir.resolve("custody"),members,wal)) {
                    DurableWalCommitQuorum.Certificate cert=custody.highestVerified();
                    if(cert==null)throw new IllegalStateException("read-only signed head missing");
                    if(cert.votes.size()!=2 ||cert.committedSequence<1)
                        throw new IllegalStateException("two independent signed voting proofs required");
                    String a=cert.votes.get(0).node,b=cert.votes.get(1).node;
                    if(a.equals(b)||!Arrays.asList(a,b).containsAll(Arrays.asList("TradeSvrA","TradeSvrB")))
                        throw new IllegalStateException("same-node attestation forbidden");
                    System.out.println("COMMON_READ_ONLY_RSA_QUORUM_PASS partition="+partition+
                        " commit="+cert.committedSequence+" config="+config+
                        " votes="+cert.votes.size()+" hash="+cert.commitPrefixSha256);
                    return;
                }
            }catch(Exception e){failure=e;}
        }
        throw new IllegalStateException("none of original signed membership digests verified",failure);
    }
}
