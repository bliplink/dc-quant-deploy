import java.lang.instrument.Instrumentation;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;

/** Read every actual Primary pending index, irrespective of product symbol. */
public final class T554OrderAllPartitionsSettlementReadAgent {
    public static void agentmain(String arguments, Instrumentation unused) throws Exception {
        String[] args=arguments.split(",",-1);
        if(args.length!=2 ||!args[1].matches("[A-Z0-9]{6}(:[A-Z0-9]{6}){0,63}"))
            throw new IllegalArgumentException("Bounded original cohort required");
        Path output=Paths.get(args[0]);
        if(!output.isAbsolute() ||Files.exists(output))throw new IllegalArgumentException("Fresh absolute output required");
        Set<String> locations=new HashSet<>(Arrays.asList(args[1].split(":")));
        if(locations.size()!=args[1].split(":").length)throw new IllegalArgumentException("Duplicate cohort");
        Class<?> holder=Class.forName("com.app.dc.signal.SpringContextHolder");
        Class<?> routing=Class.forName("com.app.dc.service.state.OrderPartitionRuntime");
        Object router=holder.getMethod("getBean",Class.class).invoke(null,routing);
        Class<?> type=Class.forName("com.app.dc.service.state.OrderCertifiedMatchOutbox");
        Object outbox=holder.getMethod("getBean",Class.class).invoke(null,type);
        Class<?> modes=Class.forName("com.app.dc.service.symbol.SymbolRuleFacade");
        Object matchingModes=holder.getMethod("getBean",Class.class).invoke(null,modes);
        String node=(String)routing.getMethod("getLocalNodeName").invoke(router);
        if(node==null ||!node.matches("[A-Za-z0-9_-]{1,64}"))throw new IllegalStateException("Invalid physical node");
        List<?> assignments=(List<?>)routing.getMethod("assignmentsSnapshot").invoke(router);
        if(assignments.size()!=256)throw new IllegalStateException("Complete actual census required");
        Set<String> seen=new HashSet<>();StringBuilder result=new StringBuilder();
        long now=System.currentTimeMillis();int total=0;
        for(Object assignment:assignments){
            String partition=(String)assignment.getClass().getMethod("getPartitionId").invoke(assignment);
            if(partition==null ||!partition.matches("P[0-9]{3}") ||Integer.parseInt(partition.substring(1))>=256
                    ||!seen.add(partition))throw new IllegalStateException("Invalid or duplicate physical partition");
            if(!(Boolean)routing.getMethod("isPrimary",String.class).invoke(router,partition))continue;
            long epoch=(Long)assignment.getClass().getMethod("getEpoch").invoke(assignment);
            if(epoch<2 ||!node.equals(assignment.getClass().getMethod("getPrimary").invoke(assignment)))
                throw new IllegalStateException("Current Primary identity differs");
            List<?> pending=(List<?>)type.getMethod("pendingPartition",String.class).invoke(outbox,partition);
            total+=pending.size();
            if(total>20000)throw new IllegalStateException("Complete bounded pending read exceeded");
            for(Object item:pending){
                Object settlement=item.getClass().getMethod("settlement").invoke(item);
                List<?> reports=(List<?>)settlement.getClass().getMethod("reports").invoke(settlement);
                if(reports.isEmpty())throw new IllegalStateException("Pending match has no reports");
                Object first=reports.get(0);
                String location=(String)first.getClass().getMethod("getLocation").invoke(first);
                if(!locations.contains(location))continue;
                String symbol=(String)first.getClass().getMethod("getSecurityID").invoke(first);
                if(symbol==null ||!symbol.matches("[A-Za-z0-9_-]{1,64}"))
                    throw new IllegalStateException("Invalid business product identity");
                String mode=(String)modes.getMethod("matchingMode",String.class,String.class)
                        .invoke(matchingModes,location,symbol);
                if(!"TRADE".equals(mode) &&!"ORDER_ONLY".equals(mode))
                    throw new IllegalStateException("Unknown pending match business mode");
                boolean confirmed=(Boolean)item.getClass().getMethod("hasLocalSettlementConfirmation").invoke(item);
                if("ORDER_ONLY".equals(mode) &&confirmed)
                    throw new IllegalStateException("Order-only retained delivery has a financial receipt");
                Object frame=item.getClass().getMethod("originalCommittedFrame").invoke(item);
                long timestamp=(Long)frame.getClass().getMethod("getTimestamp").invoke(frame);
                if(timestamp<=0 ||timestamp>now+5000
                        ||!partition.equals(frame.getClass().getMethod("getPartitionId").invoke(frame)))
                    throw new IllegalStateException("Invalid persisted match partition or timestamp");
                result.append("ORDER_ONLY".equals(mode)?"ORDER_ONLY_RETAINED\t":"MATCH\t")
                        .append(location).append('\t').append(partition).append('\t')
                        .append("ORDER_ONLY".equals(mode)?symbol:Boolean.toString(confirmed))
                        .append('\t').append(Math.max(0,now-timestamp)).append('\t')
                        .append(item.getClass().getMethod("getEpoch").invoke(item)).append('\t')
                        .append(item.getClass().getMethod("getSeq").invoke(item)).append('\n');
            }
            if(!(Boolean)routing.getMethod("isPrimary",String.class).invoke(router,partition)
                    ||epoch!=(Long)routing.getMethod("epoch",String.class).invoke(router,partition))
                throw new IllegalStateException("Primary changed during read");
            result.append("PARTITION_OWNER\t").append(partition).append('\t').append(node).append('\t')
                    .append(epoch).append('\n');
        }
        Files.write(output,result.toString().getBytes(StandardCharsets.US_ASCII),
                StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE);
    }
}
