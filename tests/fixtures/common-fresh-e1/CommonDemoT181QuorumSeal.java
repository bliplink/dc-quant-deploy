import com.app.common.replication.*;
import com.app.common.zk.ZookeeperClient;
import org.apache.zookeeper.data.Stat;
import java.nio.file.*;
import java.security.*;
import java.security.spec.X509EncodedKeySpec;
import java.util.*;

/**
 * T181 real original Genesis 256/256 two-voter quorum validation & seal.
 * Reads ONLY already-issued A and B voter RSA certificates; never signs
 * for either node or grants READY. Production Common must still authorize
 * any subsequent business admission.
 */
public final class CommonDemoT181QuorumSeal {
  static final String RSA="/read-only-original-rsa/public/";
  static final Path ROOT=Paths.get("/srv/dc/data/common-t181-born");
  static final String NS="/otc/demo-t181-fresh-20261027";
  static PublicKey key(String alias)throws Exception{
    return KeyFactory.getInstance("RSA").generatePublic(new X509EncodedKeySpec(
      Files.readAllBytes(Paths.get(RSA+alias+".pub.der"))));
  }
  static final class VerifiedShard {
    final String name;
    final byte[] image;
    final DurableWalCommitQuorum.Membership members;
    final List<CommonCertifiedGenesisQuorum.Receipt> votes;
    VerifiedShard(String n,byte[] bytes,DurableWalCommitQuorum.Membership m,
       List<CommonCertifiedGenesisQuorum.Receipt> v){name=n;image=bytes;members=m;votes=v;}
  }
  public static void main(String[] args)throws Exception{
    if(args.length!=1 || !Arrays.asList("OrderSvr","TradeSvr").contains(args[0]))
      throw new IllegalArgumentException("OrderSvr or TradeSvr");
    String service=args[0],kind="OrderSvr".equals(service)?"order":"trade";
    String a=service+"A",b=service+"B",ns=NS+"/"+kind;
    PublicKey pubA=key("CommonHaDemoA"),pubB=key("CommonHaDemoB");
    ZookeeperClient zk=new ZookeeperClient("127.0.0.1:32181",null,null);
    List<VerifiedShard> approved=new ArrayList<>();
    try{
      Stat version=new Stat();
      Object raw=zk.readData(ns+"/manifest",version);
      ZkNodeScopedControlPlane.Manifest m=ZkNodeScopedControlPlane.Manifest.parse(String.valueOf(raw));
      if(version.getVersion()!=0 || m.generation!=1 || m.assignments.size()!=256)
        throw new IllegalStateException("not virgin Common manifest");
      Stat aLease=new Stat(),bLease=new Stat();
      zk.readData(ns+"/leases/"+a,aLease);zk.readData(ns+"/leases/"+b,bLease);
      if(aLease.getEphemeralOwner()<=0 || bLease.getEphemeralOwner()<=0
          || aLease.getEphemeralOwner()==bLease.getEphemeralOwner())
        throw new IllegalStateException("missing independently owned original voter sessions");
      for(int i=0;i<256;i++){
        String p=String.format(Locale.ROOT,"P%03d",i);
        ZkNodeScopedControlPlane.Assignment assignment=m.assignments.get(p);
        if(assignment==null || assignment.ready || assignment.partition.epoch!=1
              || assignment.partition.policy!=DurableWalAckPolicy.STRICT_QUORUM)
          throw new IllegalStateException("non virgin original partition "+p);
        DurableWalCommitQuorum.Membership members=new DurableWalCommitQuorum.Membership(
            service,p,assignment.partition.primary,1,1,Arrays.asList(
                new DurableWalCommitQuorum.Member(a,"MacDockerSlotA",pubA),
                new DurableWalCommitQuorum.Member(b,"MacDockerSlotB",pubB)));
        Path aPath=ROOT.resolve(service).resolve(a).resolve(p);
        Path bPath=ROOT.resolve(service).resolve(b).resolve(p);
        byte[] image=Files.readAllBytes(aPath.resolve("node-voter/original-e1-"+a+".genesis"));
        byte[] replica=Files.readAllBytes(bPath.resolve("node-voter/original-e1-"+b+".genesis"));
        if(!MessageDigest.isEqual(image,replica))
          throw new IllegalStateException("A/B original business snapshot mismatch "+p);
        String digest=SnapshotTransferIntegrity.sha256(image);
        List<CommonCertifiedGenesisQuorum.Receipt> votes=Arrays.asList(
           CommonCertifiedGenesisQuorum.Receipt.fromWire(a,digest,
               Files.readAllBytes(aPath.resolve("receipts/"+a+".rsa2048"))),
           CommonCertifiedGenesisQuorum.Receipt.fromWire(b,digest,
               Files.readAllBytes(bPath.resolve("receipts/"+b+".rsa2048"))));
        CommonCertifiedGenesisQuorum.verify(members,image,votes);
        Map<String,Path> roots=new LinkedHashMap<>();
        roots.put(a,ROOT.resolve(service).resolve(a).resolve("original-wal").resolve(p));
        roots.put(b,ROOT.resolve(service).resolve(b).resolve("original-wal").resolve(p));
        CommonOriginalE1ZeroAckBirthEvidence zero=new CommonOriginalE1ZeroAckBirthEvidence(
          ns,digest,roots);
        zero.requireOriginalPhysicalZeroAckWal(members,members.members.get(a));
        zero.requireOriginalPhysicalZeroAckWal(members,members.members.get(b));
        approved.add(new VerifiedShard(p,image,members,votes));
      }
      System.out.println("T181_ORIGINAL_TWO_VOTER_PRESEAL_VERIFIED service="+service
            +" shards="+approved.size()+" zkv="+version.getVersion()
            +" ready=false");
      Path sealed=ROOT.resolve(service).resolve("sealed");
      if(Files.exists(sealed))
        throw new IllegalStateException("Original signed sealed directory cannot be overwritten");
      Files.createDirectories(sealed);
      for(VerifiedShard shard:approved){
        Path target=sealed.resolve(shard.name);
        CommonCertifiedGenesisQuorum.sealAndVerify(target,shard.members,
                shard.image,shard.votes);
      }
      for(VerifiedShard shard:approved)
        CommonCertifiedGenesisQuorum.reopen(sealed.resolve(shard.name),shard.members);
      System.out.println("T181_ORIGINAL_256_GENESIS_DUAL_RSA_QUORUM_FSYNC_PASS service="+service
              +" shards=256 signerA="+a+" signerB="+b+" businessReady=false");
    }finally{zk.close();}
  }
}
