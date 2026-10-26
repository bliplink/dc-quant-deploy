package com.app.dc.service.state;

import com.app.common.replication.*;
import com.alibaba.fastjson2.JSON;
import java.io.*;
import java.lang.reflect.Field;
import java.nio.file.*;
import java.security.*;
import java.security.spec.*;
import java.util.*;

/** T156 explicitly read-only auxiliary actual-service-domain JVM probe.
 * Original RSA-voter E1 Genesis + real Order/Trade managers. NOT Spring,
 * signed physical zero WAL, business listener, installation or READY.
 */
import com.app.dc.service.order.OrderManager;
import com.app.dc.service.order.OrderBook;
import com.app.dc.service.order.Order;
public final class T156OrderRealDomainSnapshotProbe {
    private static String alias(String node){
        if(node.endsWith("A"))return "CommonHaDemoA";
        if(node.endsWith("B"))return "CommonHaDemoB";
        if(node.endsWith("C"))return "CommonHaDemoC";
        throw new IllegalArgumentException("unexpected original voter");
    }
    private static PublicKey voterKey(String node)throws Exception{
        byte[] bytes=Files.readAllBytes(Paths.get("/read-only-original-rsa/public",alias(node)+".pub.der"));
        return KeyFactory.getInstance("RSA").generatePublic(new X509EncodedKeySpec(bytes));
    }
    private static DurableWalCommitQuorum.Membership original(String service,String p,
        String a,String b)throws Exception{
        return new DurableWalCommitQuorum.Membership(service,p,a,1,1,Arrays.asList(
            new DurableWalCommitQuorum.Member(a,"t150-isolated-volume-"+a,voterKey(a)),
            new DurableWalCommitQuorum.Member(b,"t150-isolated-volume-"+b,voterKey(b))));
    }
    private static void inject(Object target,String field,Object obj)throws Exception{
        Field f=target.getClass().getDeclaredField(field);f.setAccessible(true);f.set(target,obj);
    }
    private static StateMachineRecoveryCoordinator.RecoveryRequest request(
        String p,CommonCertifiedGenesisQuorum.Verified signed,Path root){
        return new StateMachineRecoveryCoordinator.RecoveryRequest(p,0,0,1,0,0,1,0,
            1,0,0,1,0,root.resolve("sealed/genesis-e1.snapshot"),
            signed.originalSha256,signed.snapshotBytes,false);
    }
    private static CommonCertifiedGenesisQuorum.Verified reopen(String service,String p,
        String a,String b,String local)throws Exception{
        if(!local.equals(a)&&!local.equals(b))throw new IllegalArgumentException("unassigned physical voter");
        DurableWalCommitQuorum.Membership old=original(service,p,a,b);
        Path root=Paths.get("/srv/dc/data/t150-original-genesis",p);
        CommonCertifiedGenesisQuorum.Verified signed=
            CommonCertifiedGenesisQuorum.reopen(root.resolve("sealed"),old);
        CommonDurableGenesisVoterImage own=new CommonDurableGenesisVoterImage(
            root.resolve("node-voter"),old,local);
        if(!MessageDigest.isEqual(signed.originalImage(),own.readCertifiedLocalImage()))
            throw new IOException("local original physical voter image differs from signed Genesis");
        return signed;
    }
    private static byte[] snapshot(ReplicatedStateMachine sm)throws IOException{
        ByteArrayOutputStream output=new ByteArrayOutputStream();
        sm.snapshot((data,off,len)->output.write(data,off,len));
        return output.toByteArray();
    }

    public static void main(String[] args)throws Exception{
        if(args.length!=4)throw new IllegalArgumentException("partition originalPrimary originalReplica local");
        String p=args[0],a=args[1],b=args[2],local=args[3];
        if(!p.matches("P[0-9]{3}"))throw new IllegalArgumentException("invalid partition");
        CommonCertifiedGenesisQuorum.Verified signed=reopen("OrderSvr",p,a,b,local);
        OrderPartitionRuntime runtime=new OrderPartitionRuntime(){
            @Override public String partitionId(String location,String market,String security){return p;}
        };
        OrderManager manager=new OrderManager();
        OrderSnapshotManager capture=new OrderSnapshotManager();
        inject(capture,"runtime",runtime);inject(capture,"orderManager",manager);
        OrderStateRecovery apply=new OrderStateRecovery();
        inject(apply,"runtime",runtime);inject(apply,"orderManager",manager);
        StateMachineRecoveryCoordinator.RecoveryRequest head=request(p,signed,
            Paths.get("/srv/dc/data/t150-original-genesis",p));
        OrderRecoveryStateMachine business=new OrderRecoveryStateMachine(head,capture,apply);
        byte[] bytes=snapshot(business);
        if(!MessageDigest.isEqual(signed.originalImage(),bytes))
            throw new IOException("actual Order business-state manager differs from dual-RSA Genesis");
        business.restore(new ReplicatedStateMachine.ChunkSource(){
            private int offset;
            @Override public int read(byte[] dst,int off,int len){
                if(offset>=bytes.length)return -1;
                int n=Math.min(len,bytes.length-offset);
                System.arraycopy(bytes,offset,dst,off,n);offset+=n;return n;
            }
        });
        business.finishReplay();
        if(!manager.getAllOrder().isEmpty())
            throw new IllegalStateException("fresh Order restore yielded unexpected order");
        OrderBook<Order> actualBook=manager.ensureOrderBook("BTCUSDT","4","TEST");
        actualBook.setLastUpdateId(42L);
        OrderRecoveryStateMachine altered=new OrderRecoveryStateMachine(head,capture,apply);
        if(MessageDigest.isEqual(signed.originalImage(),snapshot(altered)))
            throw new IllegalStateException("NONEMPTY_ORDER_BOOK_FALSELY_MATCHED_SIGNED_EMPTY_GENESIS");
        System.out.println("T156_ORDER_NONEMPTY_BUSINESS_DENIED_ORIGINAL_EMPTY_RSA_PASS partition="+p+" node="+local);
        System.out.println("T156_IN_CONTAINER_ORDER_BUSINESS_CAPTURE_AND_RESTORE_ORIGINAL_RSA_PASS"
            +" partition="+p+" node="+local+" sha="+signed.originalSha256);
        System.out.println("T156_NO_READY_ORIGINAL_WAL_ATTESTATION: auxiliary JVM only, no Common ZK lease");
    }
}