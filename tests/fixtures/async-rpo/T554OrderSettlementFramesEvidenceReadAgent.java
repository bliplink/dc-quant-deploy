import java.lang.instrument.Instrumentation;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;

/** Read-only evidence of an existing, bounded, Common-replayed pending index.
 * Does not install a transformer or dispatch/apply/acknowledge any command. */
public final class T554OrderSettlementFramesEvidenceReadAgent {
    public static void agentmain(String arguments, Instrumentation unused) throws Exception {
        String[] args = arguments.split(",", -1);
        if (args.length != 3 || !args[1].matches("P[0-9]{3}") || !args[2].matches("[A-Z0-9]{6}"))
            throw new IllegalArgumentException("Bounded partition/tenant read required");
        Path output = Paths.get(args[0]);
        if (!output.isAbsolute() || Files.exists(output)) throw new IllegalArgumentException("New absolute output required");
        Class<?> type = Class.forName("com.app.dc.service.state.OrderCertifiedMatchOutbox");
        Object outbox = Class.forName("com.app.dc.signal.SpringContextHolder")
                .getMethod("getBean", Class.class).invoke(null, type);
        List<?> pending = (List<?>) type.getMethod("pendingPartition", String.class).invoke(outbox, args[1]);
        if (pending.size() > 1024) throw new IllegalStateException("Incomplete bounded observation");
        StringBuilder rows = new StringBuilder();
        for (Object item : pending) {
            if ((Boolean) item.getClass().getMethod("hasLocalSettlementConfirmation").invoke(item)) continue;
            Object envelope = item.getClass().getMethod("settlement").invoke(item);
            List<?> reports = (List<?>) envelope.getClass().getMethod("reports").invoke(envelope);
            if (reports.isEmpty()) throw new IllegalStateException("Missing original reports");
            Object first = reports.get(0);
            if (!args[2].equals(first.getClass().getMethod("getLocation").invoke(first))) continue;
            String key = (String) item.getClass().getMethod("getMatchKey").invoke(item);
            if (key == null || key.isEmpty() || key.length() > 300)
                throw new IllegalStateException("Unexpected match identity");
            Object frame = item.getClass().getMethod("originalCommittedFrame").invoke(item);
            byte[] raw = ((String) frame.getClass().getMethod("encode").invoke(frame)).getBytes(StandardCharsets.UTF_8);
            if (raw.length > 1024 * 1024) throw new IllegalStateException("Oversized evidence frame");
            StringBuilder digest = new StringBuilder();
            for (byte b : MessageDigest.getInstance("SHA-256").digest(raw)) digest.append(String.format("%02x", b & 255));
            rows.append(Base64.getEncoder().encodeToString(key.getBytes(StandardCharsets.UTF_8))).append('\t').append(item.getClass().getMethod("getEpoch").invoke(item))
                    .append('\t').append(item.getClass().getMethod("getSeq").invoke(item)).append('\t')
                    .append(digest).append('\t').append(Base64.getEncoder().encodeToString(raw)).append('\n');
        }
        Files.write(output, rows.toString().getBytes(StandardCharsets.US_ASCII),
                StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);
    }
}
