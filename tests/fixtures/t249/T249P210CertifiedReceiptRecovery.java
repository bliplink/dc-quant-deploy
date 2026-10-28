import com.app.common.replication.*;
import com.app.common.zk.ZookeeperClient;
import java.io.*;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.file.*;
import java.security.*;
import java.security.spec.*;
import java.util.*;

/**
 * Demo-only, offline, one physical RSA identity per JVM.
 *
 * AUTHORIZED: Common ZK node grant; TWO original physical signed Custody
 * attestations; all current and previous RSA quorum signatures.
 * FORBIDDEN: fake READY, fabricate votes, change WAL/HEAD/CommitIndex,
 * overwrite prior receipt ledger without independent byte-identical archive.
 */
public final class T249P210CertifiedReceiptRecovery {
    private static final long CURRENT=35427L, PREVIOUS=35426L;
    private static final String SVC="OrderSvr", PART="P210";
    private static final String NS="/otc/demo-t181-fresh-20261027/order";
    private static final Path DATA=Paths.get("/srv/dc/data/common-t182-ready/OrderSvr");
    private static final Path PUBLIC=Paths.get("/read-only-original-rsa/public");
    private static final Path PROOF=Paths.get("/t249/proof");
    private static final Path ARCHIVE=Paths.get("/t249/archive");
    private static final String PRIMARY="OrderSvrA", REPLICA="OrderSvrB";

    private static void require(boolean ok,String message)throws IOException {
        if(!ok)throw new IOException("T249 DENIED: "+message);
    }
    private static Path nodeRoot(String node) {
        return DATA.resolve(node).resolve(SVC).resolve(node).resolve(PART).resolve("epoch-2");
    }
    private static PublicKey publicKey(String alias)throws Exception {
        byte[] der=Files.readAllBytes(PUBLIC.resolve(alias+".pub.der"));
        return KeyFactory.getInstance("RSA").generatePublic(new X509EncodedKeySpec(der));
    }
    private static DurableWalCommitQuorum.Membership membership()throws Exception {
        return new DurableWalCommitQuorum.Membership(SVC,PART,PRIMARY,2L,2L,
            Arrays.asList(
              new DurableWalCommitQuorum.Member(PRIMARY,"MacDockerSlotA",publicKey("CommonHaDemoA")),
              new DurableWalCommitQuorum.Member(REPLICA,"MacDockerSlotB",publicKey("CommonHaDemoB"))));
    }
    private static void forceDir(Path dir)throws IOException {
        try(FileChannel c=FileChannel.open(dir,StandardOpenOption.READ)){c.force(true);}
    }
    private static byte[] encode(DurableWalCustodyQuorum.Receipt r)throws Exception {
        ByteArrayOutputStream b=new ByteArrayOutputStream();
        try(DataOutputStream d=new DataOutputStream(b)){
            d.writeUTF(r.node);d.writeUTF(r.partition);
            d.writeUTF(r.oldMembershipHash);d.writeUTF(r.walPrefixHash);
            d.writeLong(r.oldEpoch);d.writeLong(r.sequence);
            byte[] sig=r.signature();d.writeInt(sig.length);d.write(sig);
        }
        return b.toByteArray();
    }
    private static DurableWalCustodyQuorum.Receipt decode(Path file)throws Exception {
        byte[] raw=Files.readAllBytes(file);
        require(raw.length>0 && raw.length<4096,"unsafe external receipt file");
        try(DataInputStream in=new DataInputStream(new ByteArrayInputStream(raw))){
            String node=in.readUTF(),partition=in.readUTF(),member=in.readUTF(),sha=in.readUTF();
            long epoch=in.readLong(),sequence=in.readLong();
            int len=in.readInt();require(len==256,"wrong RSA receipt size");
            byte[] signature=new byte[len];in.readFully(signature);
            require(in.read()==-1,"trailing external receipt");
            return DurableWalCustodyQuorum.Receipt.fromWire(
                    node,partition,member,sha,epoch,sequence,signature);
        }
    }
    private static DurableWalCommitQuorum.Certificate previousCertificate(
            DurableWalCommitQuorum.Membership membership)throws Exception {
        Path commit=nodeRoot(PRIMARY).resolve("commit-index")
            .resolve(String.format(Locale.ROOT,"commit-%020d.bin",PREVIOUS));
        require(Files.isRegularFile(commit,LinkOption.NOFOLLOW_LINKS),"old signed CommitIndex absent");
        byte[] raw=Files.readAllBytes(commit);
        try(DataInputStream in=new DataInputStream(new ByteArrayInputStream(raw))){
            require(in.readInt()==0x4f544357 && in.readInt()==1,"unknown CommitIndex format");
            require(membership.digest.equals(in.readUTF()),"prior membership mismatch");
            long epoch=in.readLong(),seq=in.readLong(),priorSeq=in.readLong();
            String walHash=in.readUTF(),priorHash=in.readUTF();
            require(epoch==2 && seq==PREVIOUS && priorSeq==PREVIOUS-1
                    && walHash.matches("[a-f0-9]{64}") && !priorHash.isEmpty(),
                    "old certificate sequence/chain mismatch");
            int count=in.readInt();require(count==2,"not independent original CommitIndex quorum");
            List<DurableWalCommitQuorum.Receipt> votes=new ArrayList<>();
            for(int i=0;i<count;i++){
                String node=in.readUTF(),part=in.readUTF();
                long vEpoch=in.readLong(),vSeq=in.readLong();
                String vHash=in.readUTF(),vMembership=in.readUTF();
                int length=in.readInt();require(length==256,"wrong RSA vote size");
                byte[] sig=new byte[length];in.readFully(sig);
                votes.add(DurableWalCommitQuorum.Receipt.fromWire(
                    node,part,vEpoch,vSeq,vHash,vMembership,sig));
            }
            require(in.read()==-1,"old cert trailing bytes");
            return DurableWalCommitQuorum.verify(membership,seq,walHash,votes);
        }
    }
    private static void proveActualOldPrefix(Path walPath,
            DurableWalCommitQuorum.Certificate previous)throws Exception {
        MessageDigest digest=MessageDigest.getInstance("SHA-256");
        try(DataInputStream stream=new DataInputStream(
                new BufferedInputStream(Files.newInputStream(walPath)))){
            for(long i=1;i<=PREVIOUS;i++){
                byte[] header=new byte[28];
                stream.readFully(header);
                ByteBuffer f=ByteBuffer.wrap(header);
                int magic=f.getInt();
                long epoch=f.getLong(),seq=f.getLong();
                int len=f.getInt(),crc=f.getInt();
                require(magic==0x43425731 && epoch==2 && seq==i && len>0
                        && len<=1048576,"historic WAL corruption");
                byte[] payload=new byte[len];stream.readFully(payload);
                java.util.zip.CRC32 verified=new java.util.zip.CRC32();
                ByteBuffer checksum=ByteBuffer.allocate(16);
                checksum.putLong(epoch).putLong(seq);
                verified.update(checksum.array());verified.update(payload);
                require((int)verified.getValue()==crc,"historic WAL CRC incorrect");
                digest.update(header);digest.update(payload);
            }
        }
        StringBuilder h=new StringBuilder();
        for(byte b:digest.digest())h.append(String.format(Locale.ROOT,"%02x",b&255));
        require(h.toString().equals(previous.commitPrefixSha256),"previous signed WAL prefix altered");
    }
    private static PrivateKey keyFor(String node)throws Exception {
        String slot=PRIMARY.equals(node)?"a":"b";
        Path file=Paths.get("/read-only-original-rsa/"+slot+"/node.pk8");
        require(Files.isRegularFile(file,LinkOption.NOFOLLOW_LINKS),"original node private key unavailable");
        return KeyFactory.getInstance("RSA").generatePrivate(
            new PKCS8EncodedKeySpec(Files.readAllBytes(file)));
    }
    private static void attest(String node,DurableWalCommitQuorum.Membership membership,
            DurableWalCertificateCustody custody)throws Exception {
        DurableWalCommitQuorum.Certificate head=custody.highestVerified();
        require(head!=null && head.committedSequence==CURRENT,
                "current RSA custody head not signed at expected sequence");
        DurableWalCustodyQuorum.Receipt receipt=
                custody.signInstalled(node,keyFor(node));
        DurableWalCustodyQuorum.requireValidReceipt(membership,head,receipt);
        require(receipt.node.equals(node) && receipt.sequence==CURRENT,"unexpected signer");
        Path target=PROOF.resolve(node+".custody-receipt");
        try(FileChannel channel=FileChannel.open(target,
                StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE)){
            ByteBuffer encoded=ByteBuffer.wrap(encode(receipt));
            while(encoded.hasRemaining())channel.write(encoded);
            channel.force(true);
        }
        forceDir(PROOF);
        System.out.println("T249_AUTHENTICATED_INDEPENDENT_CUSTODY_RECEIPT_PASS node="+node
                +" seq="+receipt.sequence);
    }
    private static void finish(String node,DurableWalCommitQuorum.Membership membership,
            DurableWalCertificateCustody custody,Path path)throws Exception {
        require(Files.isRegularFile(ARCHIVE.resolve(node+"-receipt-quorum.bin"),
                LinkOption.NOFOLLOW_LINKS),"prior original ledger evidence missing");
        DurableWalCommitQuorum.Certificate last=custody.highestVerified();
        require(last!=null && last.committedSequence==CURRENT,
                "current exact physical Custody HEAD not installed");
        DurableWalCommitQuorum.Certificate previous=previousCertificate(membership);
        proveActualOldPrefix(path.resolve("business.wal"),previous);
        List<DurableWalCustodyQuorum.Receipt> receipts=Arrays.asList(
            decode(PROOF.resolve(PRIMARY+".custody-receipt")),
            decode(PROOF.resolve(REPLICA+".custody-receipt")));
        DurableWalCustodyQuorum.CustodiedCertificate quorum=
            DurableWalCustodyQuorum.verify(membership,last,receipts);
        require(quorum.physicalCustodians==2 && quorum.sequence==CURRENT,
                "current independent quorum not certified");
        Path ledgerDir=path.resolve("custody-ledger");
        try(DurableWalCustodyReceiptLedger ledger=
                DurableWalCustodyReceiptLedger.openForCertifiedCrashCompletion(
                    ledgerDir,membership,custody,previous,
                    ARCHIVE.resolve(node+"-receipt-quorum.bin"))){
            require(ledger.persist(last,receipts)==CURRENT,
                    "authenticated postinstall ledger not durably stored");
            require(ledger.requireRecovered(last).size()==2,
                    "Common recovered ledger still not valid");
        }
        forceDir(ledgerDir);
        System.out.println("T249_CERTIFIED_LEDGER_CRASH_COMPLETION_PASS node="+node
                +" seq="+CURRENT);
    }
    public static void main(String[] args)throws Exception {
        require(args.length==2 && ("attest".equals(args[0]) || "finish".equals(args[0]))
            && (PRIMARY.equals(args[1]) || REPLICA.equals(args[1])),
            "usage: attest|finish OrderSvrA|OrderSvrB");
        String mode=args[0],node=args[1];
        DurableWalCommitQuorum.Membership membership=membership();
        Path path=nodeRoot(node);
        ZookeeperClient zk=new ZookeeperClient("127.0.0.1:32181",null,null);
        try {
            ZkNodeScopedControlPlane plane=new ZkNodeScopedControlPlane(zk,node,
                NS+"/manifest",NS+"/leases/"+node,"T249Physical"+node,12000L,0L);
            NodePartitionGrantTable table=plane.newGrantTable();
            try(NodeClusterControlManager manager=new NodeClusterControlManager(
                    node,plane,table,1000L)){
                plane.attach(manager);
                manager.start();
                manager.awaitInitialCertifiedPartitionCensus(15000L);
                DurableWalCertificateCustody.Authority authority=old->{
                    require(old.digest.equals(membership.digest)
                            && old.epoch==2,"old epoch or pinned membership changed");
                    NodePartitionGrantTable.Permit permit=PRIMARY.equals(node)
                            ?manager.requirePrimary(PART,2,DurableWalAckPolicy.STRICT_QUORUM)
                            :manager.requireReplica(PART,2,DurableWalAckPolicy.STRICT_QUORUM);
                    permit.requireCurrent();
                };
                authority.requireOldEpochAuthorized(membership);
                try(CommonFileBusinessWal wal=new CommonFileBusinessWal(
                        path.resolve("business.wal"),2L);
                    DurableWalCertificateCustody custody=new DurableWalCertificateCustody(
                        path.resolve("custody"),membership,wal,authority)){
                    require(wal.forcedSequence()==CURRENT,"node WAL not at signed sequence");
                    if("attest".equals(mode))attest(node,membership,custody);
                    else finish(node,membership,custody,path);
                }
            }
        }finally { zk.close(); }
    }
}