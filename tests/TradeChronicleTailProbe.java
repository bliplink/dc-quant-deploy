import java.io.File;
import net.openhft.chronicle.queue.ChronicleQueue;
import net.openhft.chronicle.queue.ExcerptTailer;
import net.openhft.chronicle.queue.TailerDirection;
import net.openhft.chronicle.queue.impl.single.SingleChronicleQueueBuilder;

/**
 * Read-only Chronicle Queue index/tailer probe. Must be run against an OFFLINE
 * COPY of one partition directory. No record writes, no journal rebase,
 * no recovery or READY changes. Never run against a live writer.
 *
 * Usage: java -cp <service-lib-wildcard>:/tmp <class> /evidence/P200
 */
public final class TradeChronicleTailProbe {
    public static void main(String[] args) {
        if (args.length != 1) throw new IllegalArgumentException("one isolated copy path required");
        File path = new File(args[0]);
        if (!path.isDirectory()) throw new IllegalArgumentException("missing isolated evidence directory");
        try (ChronicleQueue queue = SingleChronicleQueueBuilder.single(path).readOnly(true).build()) {
            long first = queue.firstIndex();
            long last = queue.lastIndex();
            ExcerptTailer end = queue.createTailer().direction(TailerDirection.BACKWARD).toEnd();
            String lastBody = end.readText();
            long lastTailerIndex = end.index();
            ExcerptTailer scan = queue.createTailer();
            long count = 0L;
            long highestSeq = -1L;
            long firstSeq = -1L;
            long discontinuities = 0L;
            long decodeFailures = 0L;
            String body;
            while ((body = scan.readText()) != null) {
                String[] chunks = body.split("\\t", -1);
                if (chunks.length != 7) {
                    decodeFailures++;
                    continue;
                }
                long seq;
                try { seq = Long.parseLong(chunks[2]); }
                catch (NumberFormatException invalid) { decodeFailures++; continue; }
                if (count == 0) firstSeq = seq;
                else if (seq != highestSeq + 1L) discontinuities++;
                highestSeq = seq;
                count++;
                if (count > 2000000L) throw new IllegalStateException("probe scan bound exceeded");
            }
            long afterScanIndex = scan.index();
            boolean lastMovable = last >= 0 && queue.createTailer().moveToIndex(last);
            System.out.println("CHRONICLE_READ_ONLY_PROBE"
                 + " queueFirstIndex=" + first
                 + " queueLastIndex=" + last
                 + " lastMovable=" + lastMovable
                 + " backwardsTailerIndex=" + lastTailerIndex
                 + " backwardsTailerHasBody=" + (lastBody != null)
                 + " forwardRecords=" + count
                 + " firstRecordSeq=" + firstSeq
                 + " highestRecordSeq=" + highestSeq
                 + " sequenceGaps=" + discontinuities
                 + " decodeFailures=" + decodeFailures
                 + " afterScanIndex=" + afterScanIndex
                 + " COMMIT_AUTHENTICATION=NOT_CHECKED"
                 + " RESTORE_AUTHORIZED=false");
        }
    }
}
