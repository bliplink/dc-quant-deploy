import java.lang.instrument.Instrumentation;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;

/** Read existing replayed indexes on the actual Primary; never dispatch or ACK. */
public final class T554OrderCohortSettlementReadAgent {
    public static void agentmain(String arguments, Instrumentation unused) throws Exception {
        String[] args=arguments.split(",",-1);
        if(args.length!=2 ||!args[1].matches("[A-Z0-9]{6}(:[A-Z0-9]{6}){0,63}"))
            throw new IllegalArgumentException("Bounded original cohort required");
        Path output=Paths.get(args[0]);
        if(!output.isAbsolute() ||Files.exists(output))throw new IllegalArgumentException("Fresh absolute output required");
        Class<?> holder=Class.forName("com.app.dc.signal.SpringContextHolder");
        Class<?> routing=Class.forName("com.app.dc.service.state.OrderPartitionRuntime");
        Object router=holder.getMethod("getBean",Class.class).invoke(null,routing);
        Class<?> type=Class.forName("com.app.dc.service.state.OrderCertifiedMatchOutbox");
        Object outbox=holder.getMethod("getBean",Class.class).invoke(null,type);
        StringBuilder result=new StringBuilder();
        Set<String> locations=new HashSet<>();
        long now=System.currentTimeMillis();
        for(String location:args[1].split(":")){
            if(!locations.add(location))throw new IllegalArgumentException("Duplicate cohort identity");
            String partition=(String)routing.getMethod("partitionId",String.class,String.class,String.class)
                    .invoke(router,location,"4","BTCUSDT");
            if(!(Boolean)routing.getMethod("isPrimary",String.class).invoke(router,partition))continue;
            List<?> pending=(List<?>)type.getMethod("pendingPartition",String.class).invoke(outbox,partition);
            if(pending.size()>20000)throw new IllegalStateException("Incomplete bounded partition read");
            for(Object item:pending){
                Object settlement=item.getClass().getMethod("settlement").invoke(item);
                List<?> reports=(List<?>)settlement.getClass().getMethod("reports").invoke(settlement);
                if(reports.isEmpty())throw new IllegalStateException("Pending match has no reports");
                Object first=reports.get(0);
                if(!location.equals(first.getClass().getMethod("getLocation").invoke(first)))continue;
                boolean confirmed=(Boolean)item.getClass().getMethod("hasLocalSettlementConfirmation").invoke(item);
                Object frame=item.getClass().getMethod("originalCommittedFrame").invoke(item);
                long timestamp=(Long)frame.getClass().getMethod("getTimestamp").invoke(frame);
                if(timestamp<=0 ||timestamp>now+5000)throw new IllegalStateException("Invalid persisted match timestamp");
                result.append("MATCH\t").append(location).append('\t').append(partition).append('\t')
                        .append(confirmed).append('\t').append(Math.max(0,now-timestamp)).append('\t')
                        .append(item.getClass().getMethod("getEpoch").invoke(item)).append('\t')
                        .append(item.getClass().getMethod("getSeq").invoke(item)).append('\n');
            }
            if(!(Boolean)routing.getMethod("isPrimary",String.class).invoke(router,partition))
                throw new IllegalStateException("Primary changed during read");
            result.append("OWNER\t").append(location).append('\t').append(partition).append('\n');
        }
        Files.write(output,result.toString().getBytes(StandardCharsets.US_ASCII),
                StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE);
    }
}
