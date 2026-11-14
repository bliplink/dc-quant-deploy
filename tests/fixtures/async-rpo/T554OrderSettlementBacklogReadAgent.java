import java.lang.instrument.Instrumentation;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;

/** Test-only read of Common-replayed Order's existing pending index.
 * No transformer, command dispatch, ACK, state apply or financial mutation. */
public final class T554OrderSettlementBacklogReadAgent {
    public static void agentmain(String arguments,Instrumentation unused)throws Exception {
        String[] args=arguments.split(",",-1);
        if(args.length!=3 ||!args[1].matches("P[0-9]{3}") ||!args[2].matches("[A-Z0-9]{6}"))
            throw new IllegalArgumentException("Bounded partition/tenant observation required");
        Path output=Paths.get(args[0]);
        if(!output.isAbsolute() ||Files.exists(output))throw new IllegalArgumentException("New absolute output required");
        Class<?> type=Class.forName("com.app.dc.service.state.OrderCertifiedMatchOutbox");
        Object outbox=Class.forName("com.app.dc.signal.SpringContextHolder").getMethod("getBean",Class.class).invoke(null,type);
        List<?> pending=(List<?>)type.getMethod("pendingPartition",String.class).invoke(outbox,args[1]);
        if(pending.size()>1024)throw new IllegalStateException("Observed partition exceeds bounded complete read");
        int all=0,tenantPending=0,tenantFinalLocal=0;
        List<String> first=new ArrayList<>();
        for(Object item:pending){
            boolean confirmed=(Boolean)item.getClass().getMethod("hasLocalSettlementConfirmation").invoke(item);
            if(!confirmed)all++;
            Object envelope=item.getClass().getMethod("settlement").invoke(item);
            List<?> reports=(List<?>)envelope.getClass().getMethod("reports").invoke(envelope);
            if(reports.isEmpty())throw new IllegalStateException("An observed original match has no reports");
            Object report=reports.get(0);
            if(!args[2].equals(report.getClass().getMethod("getLocation").invoke(report)))continue;
            if(confirmed)tenantFinalLocal++;else {
                tenantPending++;
                if(first.size()<16){
                    String id=(String)report.getClass().getMethod("getOrderID").invoke(report);
                    if(id==null ||!id.matches("[A-Za-z0-9_-]{1,64}"))throw new IllegalStateException("Unexpected original order ID");
                    first.add(id);
                }
            }
        }
        String result="scope=READ_ONLY_REPLAYED_ORDER_INDEX_NOT_A_FINANCIAL_COMMIT_PROOF\n"
                +"partition="+args[1]+"\nlocation="+args[2]+"\ncomplete_partition_observation=true\n"
                +"partition_pending_count="+pending.size()+"\npartition_financial_unsettled="+all
                +"\ntenant_financial_unsettled="+tenantPending+"\ntenant_local_final_replication_pending="+tenantFinalLocal
                +"\nfirst_unsettled_maker_order_ids="+String.join(",",first)+"\n";
        Files.write(output,result.getBytes(StandardCharsets.US_ASCII),StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE);
    }
}
