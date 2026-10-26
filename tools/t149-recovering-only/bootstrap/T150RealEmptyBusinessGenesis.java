import com.alibaba.fastjson2.JSON;
import com.alibaba.fastjson2.JSONObject;
import com.app.common.zk.ZookeeperClient;
import com.app.common.replication.*;
import org.apache.zookeeper.data.Stat;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.security.spec.*;
import java.util.*;

/** T150 fresh, empty Order or Trade business image, original node-local durable
 * Genesis voters, strict Common RSA quorum. Never mints READY or recovery HEAD.
 * Classpath must include exactly the service's REAL snapshot domain class. */
public final class T150RealEmptyBusinessGenesis {
    private static final String RSA="/read-only-original-rsa";
    private static final String ZK="zk1:2181,zk2:2181,zk3:2181";
    private static String alias(String node){
        if(node.endsWith("A"))return "CommonHaDemoA";
        if(node.endsWith("B"))return "CommonHaDemoB";
        if(node.endsWith("C"))return "CommonHaDemoC";
        throw new IllegalArgumentException("unknown physical voter alias");
    }
    private static PublicKey publicFor(String node)throws Exception{
        return KeyFactory.getInstance("RSA").generatePublic(new X509EncodedKeySpec(
            Files.readAllBytes(Paths.get(RSA,"public",alias(node)+".pub.der"))));
    }
    private static PrivateKey myPrivate(String me)throws Exception{
        String slot=me.endsWith("A")?"a":me.endsWith("B")?"b":"c";
        return KeyFactory.getInstance("RSA").generatePrivate(new PKCS8EncodedKeySpec(
            Files.readAllBytes(Paths.get(RSA,slot,"node.pk8"))));
    }
    private static DurableWalCommitQuorum.Membership membership(String service,
            String p,String primary,String replica)throws Exception{
        return new DurableWalCommitQuorum.Membership(service,p,primary,1,1,Arrays.asList(
            new DurableWalCommitQuorum.Member(primary,"t150-isolated-volume-"+primary,
                publicFor(primary)),
            new DurableWalCommitQuorum.Member(replica,"t150-isolated-volume-"+replica,
                publicFor(replica))));
    }
    private static void validateLiveCensus(String service,String partition,
            String primary,String replica,String me)throws Exception{
        String kind="OrderSvr".equals(service)?"order":"trade";
        ZookeeperClient z=new ZookeeperClient(ZK,null,null);
        try{
            String path="/otc/t149/"+kind;
            ZkNodeScopedControlPlane.Manifest census=ZkNodeScopedControlPlane.Manifest.parse(
                String.valueOf(z.readData(path+"/manifest")));
            ZkNodeScopedControlPlane.Assignment assignment=census.assignments.get(partition);
            if(census.generation!=1 || assignment==null || assignment.ready
                    || assignment.partition.epoch!=1
                    || assignment.partition.policy!=DurableWalAckPolicy.STRICT_QUORUM
                    || !primary.equals(assignment.partition.primary)
                    || !replica.equals(assignment.partition.replica))
                throw new IllegalStateException("T150 original Common E1 manifest is not matching recovering voter census");
            Stat leaseStat=new Stat();z.readData(path+"/leases/"+me,leaseStat);
            if(leaseStat.getEphemeralOwner()<=0)
                throw new IllegalStateException("original node does not hold its actual Common ephemeral ZK lease");
        }finally{z.close();}
    }
    private static byte[] freshDomainImage(String service,String partition)throws Exception{
        String clazz="OrderSvr".equals(service)
            ?"com.app.dc.service.state.OrderPartitionSnapshot"
            :"com.app.dc.service.state.TradePartitionSnapshot";
        Object snap=Class.forName(clazz).getDeclaredConstructor().newInstance();
        Class<?> type=snap.getClass();
        type.getMethod("setPartitionId",String.class).invoke(snap,partition);
        type.getMethod("setSnapshotId",String.class).invoke(snap,partition+"-common-e1-s0");
        type.getMethod("setEpoch",long.class).invoke(snap,1L);
        type.getMethod("setSnapshotSeq",long.class).invoke(snap,0L);
        type.getMethod("setCommittedStateSeq",long.class).invoke(snap,0L);
        type.getMethod("setCommittedStateEpoch",long.class).invoke(snap,1L);
        type.getMethod("setCreatedAt",long.class).invoke(snap,1L);
        if("OrderSvr".equals(service))type.getMethod("setCommitMarkerSeq",long.class).invoke(snap,0L);
        byte[] image=JSON.toJSONBytes(snap);
        if(image==null || image.length<16 || image.length>32768)
            throw new IllegalStateException("fresh business image schema is not valid");
        JSONObject decoded=JSON.parseObject(image);
        if(!partition.equals(decoded.getString("partitionId"))
                || !"P090-common-e1-s0".replace("P090",partition).equals(decoded.getString("snapshotId"))
                || decoded.getLongValue("epoch")!=1
                || decoded.getLongValue("snapshotSeq")!=0
                || decoded.getLongValue("committedStateSeq")!=0)
            throw new IllegalStateException("invalid original service business Genesis frame");
        List<String> fields="OrderSvr".equals(service)
            ?Arrays.asList("books","clientOrderReservations")
            :Arrays.asList("locations","balances","positions","accountConfigs",
                "symbolParas","openOrders");
        for(String field:fields)
            if(!(decoded.get(field) instanceof List) || !((List<?>)decoded.get(field)).isEmpty())
                throw new IllegalStateException("original Genesis image is not an empty business state "+field);
        if("TradeSvr".equals(service)){
            JSONObject d=decoded.getJSONObject("executionDedupe");
            if(d==null || !(d.get("applied") instanceof List)
                    || !(d.get("terminalOrders") instanceof List)
                    || !d.getJSONArray("applied").isEmpty()
                    || !d.getJSONArray("terminalOrders").isEmpty())
                throw new IllegalStateException("empty Trade execution dedupe not verified");
        }
        return image;
    }
    public static void main(String[] args)throws Exception{
        if(args.length!=6)throw new IllegalArgumentException("--sign|--combine|--verify service partition primary replica myNode");
        String operation=args[0],service=args[1],p=args[2],primary=args[3],replica=args[4],me=args[5];
        if(!Arrays.asList("OrderSvr","TradeSvr").contains(service) || !p.matches("P[0-9]{3}")
                || !me.equals(primary) && !me.equals(replica))
            throw new IllegalArgumentException("invalid original service partition or local physical node");
        validateLiveCensus(service,p,primary,replica,me);
        DurableWalCommitQuorum.Membership m=membership(service,p,primary,replica);
        byte[] image=freshDomainImage(service,p);
        Path root=Paths.get("/srv/dc/data/t150-original-genesis",p);
        Path signed=root.resolve("node-voter");Path votes=root.resolve("receipts");
        Path sealed=root.resolve("sealed");
        if("--sign".equals(operation)){
            // Independent Original A/B/C business containers each have only
            // their own original private key and their own durable data root.
            if(Files.exists(root))throw new IllegalStateException("existing original voter Genesis root must never be overwritten");
            Files.createDirectories(votes);
            CommonDurableGenesisVoterImage voter=new CommonDurableGenesisVoterImage(
                signed,m,me);
            voter.writeAndFsyncOnce(image);
            CommonCertifiedGenesisQuorum.Receipt receipt=CommonCertifiedGenesisQuorum
                .signLocallyDurable(m,me,voter,myPrivate(me));
            Path proof=votes.resolve(me+".rsa2048");
            Files.write(proof,receipt.signature(),StandardOpenOption.CREATE_NEW);
            System.out.println("T150_ORIGINAL_BUSINESS_GENESIS_NODE_RSA_FSYNC_PASS service="+service+
                " partition="+p+" node="+me+" bytes="+image.length+
                " sha="+SnapshotTransferIntegrity.sha256(image));
            return;
        }
        CommonCertifiedGenesisQuorum.Receipt a=CommonCertifiedGenesisQuorum.Receipt.fromWire(
            primary,SnapshotTransferIntegrity.sha256(image),Files.readAllBytes(votes.resolve(primary+".rsa2048")));
        CommonCertifiedGenesisQuorum.Receipt b=CommonCertifiedGenesisQuorum.Receipt.fromWire(
            replica,SnapshotTransferIntegrity.sha256(image),Files.readAllBytes(votes.resolve(replica+".rsa2048")));
        if("--combine".equals(operation)){
            if(!me.equals(primary))throw new IllegalStateException("only original Primary can seal initial Gen E1");
            CommonCertifiedGenesisQuorum.sealAndVerify(sealed,m,image,Arrays.asList(a,b));
        }else if("--negative".equals(operation)){
            if(!me.equals(primary))throw new IllegalStateException("only original Primary may run quarantine tamper probe");
            byte[] badSig=b.signature();badSig[0]^=0x01;
            boolean rejectedSig=false;
            try{CommonCertifiedGenesisQuorum.verify(m,image,Arrays.asList(a,
                    CommonCertifiedGenesisQuorum.Receipt.fromWire(replica,
                        SnapshotTransferIntegrity.sha256(image),badSig)));}
            catch(Exception required){rejectedSig=true;}
            if(!rejectedSig)throw new IllegalStateException("corrupt original B voter RSA was accepted");
            // Never mutate original durable certificate: operate only on a
            // separate cloned quarantine directory, then erase clone.
            Path quarantine=root.resolve("corrupted-proof-quarantine");
            if(Files.exists(quarantine))throw new IllegalStateException("stale tamper quarantine found");
            Files.createDirectories(quarantine);
            try{
                Files.copy(sealed.resolve("genesis-e1.snapshot"),quarantine.resolve("genesis-e1.snapshot"));
                byte[] corrupt=Files.readAllBytes(sealed.resolve("genesis-e1.quorum"));
                corrupt[corrupt.length-1]^=0x01;
                Files.write(quarantine.resolve("genesis-e1.quorum"),corrupt,StandardOpenOption.CREATE_NEW);
                boolean rejectedProof=false;
                try{CommonCertifiedGenesisQuorum.reopen(quarantine,m);}
                catch(Exception required){rejectedProof=true;}
                if(!rejectedProof)throw new IllegalStateException("corrupt sealed original Genesis reopened");
            }finally{
                Files.deleteIfExists(quarantine.resolve("genesis-e1.snapshot"));
                Files.deleteIfExists(quarantine.resolve("genesis-e1.quorum"));
                Files.deleteIfExists(quarantine);
            }
            CommonCertifiedGenesisQuorum.reopen(sealed,m);
            System.out.println("T150_ORIGINAL_RSA_AND_SEALED_GENESIS_TAMPER_REJECTED_PASS service="+
                service+" partition="+p+" businessReady=false");
            return;
        }else if(!"--verify".equals(operation))throw new IllegalArgumentException("unsupported mode");
        CommonCertifiedGenesisQuorum.Verified proof=CommonCertifiedGenesisQuorum.reopen(sealed,m);
        if(!Arrays.equals(image,proof.originalImage()) || proof.originalEpoch!=1)
            throw new IllegalStateException("durable original Genesis recovered wrong Trade/Order business image");
        System.out.println("T150_ORIGINAL_BUSINESS_GENESIS_INDEPENDENT_RSA_QUORUM_PASS service="+service+
            " partition="+p+" imageSha="+proof.originalSha256+" bytes="+proof.snapshotBytes+
            " businessReady=false");
    }
}
