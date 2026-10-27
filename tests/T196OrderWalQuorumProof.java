import com.app.common.replication.*;
import java.nio.file.*;
import java.security.*;
import java.security.spec.*;
import java.util.*;
public final class T196OrderWalQuorumProof {
 static PublicKey key(Path root,String id)throws Exception {
  return KeyFactory.getInstance("RSA").generatePublic(
   new X509EncodedKeySpec(Files.readAllBytes(root.resolve(id+".pub.der"))));
 }
 public static void main(String[] args)throws Exception {
  Path physical=Paths.get(args[0]),pub=Paths.get(args[1]);
  DurableWalCommitQuorum.Membership m=new DurableWalCommitQuorum.Membership(
   "OrderSvr","P089","OrderSvrB",2,2,Arrays.asList(
   new DurableWalCommitQuorum.Member("OrderSvrA","MacDockerSlotA",key(pub,"CommonHaDemoA")),
   new DurableWalCommitQuorum.Member("OrderSvrB","MacDockerSlotB",key(pub,"CommonHaDemoB"))));
  CommonCertifiedE2ReplicaHistory.Verified verified=
   CommonCertifiedE2ReplicaHistory.openExistingReadOnly(
    physical,m,"OrderSvrA",4096,64L*1024L*1024L);
  if(verified.committedSequence!=verified.frames.size() || verified.authorizesReady())
   throw new AssertionError("unsigned or partial Order WAL unauthorized");
  System.out.println("T196_ORDER_SIGNED_E2_REAL_WAL_PASS partition=P089 commit="+
   verified.committedSequence+" SHA="+verified.sha256+
   " dualRSA=true servingAuthority=false");
 }
}
