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
import com.app.dc.service.balance.AccountBalanceFacade;
import com.app.dc.service.position.PositionFacade;
import com.app.dc.service.data.DataFacade;
import com.app.dc.service.order.OrderManager;
import com.app.dc.service.order.ExecutionDeduplicator;
public final class T156TradeRealDomainSnapshotProbe {
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
        CommonCertifiedGenesisQuorum.Verified signed=reopen("TradeSvr",p,a,b,local);
        TradePartitionRuntime runtime=new TradePartitionRuntime(){
            @Override public String partitionId(String location){return p;}
        };
        TradeBusinessSnapshotCapture capture=new TradeBusinessSnapshotCapture();
        inject(capture,"runtime",runtime);
        AccountBalanceFacade balances=new AccountBalanceFacade();
        inject(capture,"balances",balances);
        inject(capture,"positions",new PositionFacade());
        inject(capture,"data",new DataFacade());
        inject(capture,"orders",new OrderManager());
        inject(capture,"executions",new ExecutionDeduplicator());
        StateMachineRecoveryCoordinator.RecoveryRequest head=request(p,signed,
            Paths.get("/srv/dc/data/t150-original-genesis",p));
        TradeRecoveryStateMachine business=new TradeRecoveryStateMachine(
            head,new TradeRecoveryApplier(),capture);
        byte[] bytes=snapshot(business);
        if(!MessageDigest.isEqual(signed.originalImage(),bytes))
            throw new IOException("actual Trade business-state managers differ from dual-RSA Genesis");
        business.restore(new ReplicatedStateMachine.ChunkSource(){
            private int offset;
            @Override public int read(byte[] dst,int off,int len){
                if(offset>=bytes.length)return -1;
                int n=Math.min(len,bytes.length-offset);
                System.arraycopy(bytes,offset,dst,off,n);offset+=n;return n;
            }
        });
        com.app.dc.service.balance.AccountBalance populated=new com.app.dc.service.balance.AccountBalance();
        populated.setLocation("TEST");populated.setUserID("U1");
        populated.setBalance(new java.math.BigDecimal("200"));
        balances.applyRecoveredBalance(populated);
        byte[] nonempty=JSON.toJSONBytes(capture.capture(head));
        if(MessageDigest.isEqual(signed.originalImage(),nonempty))
            throw new IllegalStateException("NONEMPTY_TRADE_BALANCE_FALSELY_MATCHED_SIGNED_EMPTY_GENESIS");
        TradeRecoveryStateMachine altered=new TradeRecoveryStateMachine(
            head,new TradeRecoveryApplier(),capture);
        boolean rejected=false;
        try {snapshot(altered);}
        catch(IOException expected) {
            if(!expected.getMessage().contains("exceeds Common transfer limit"))throw expected;
            rejected=true;
        }
        if(!rejected)
            throw new IllegalStateException("NONEMPTY_TRADE_SNAPSHOT_EXCEEDED_SIGNED_BYTES_BUT_ACCEPTED");
        System.out.println("T156_TRADE_NONEMPTY_BUSINESS_DENIED_ORIGINAL_EMPTY_RSA_PASS partition="+p+" node="+local);
        System.out.println("T156_IN_CONTAINER_TRADE_BUSINESS_CAPTURE_AND_STAGED_RESTORE_ORIGINAL_RSA_PASS"
            +" partition="+p+" node="+local+" sha="+signed.originalSha256);
        System.out.println("T156_NO_READY_ORIGINAL_WAL_ATTESTATION: auxiliary JVM only; no durable journal applied");
    }
}