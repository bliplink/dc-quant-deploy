import java.io.File;
import com.app.dc.service.cluster.TradePartitionJournal;

/**
 * Forensics-only reader. Run exclusively on a COPY of an offline or fenced
 * partition journal; it opens Chronicle in writable mode and must never
 * point at a live directory. Contains no readiness or recovery operations.
 */
public final class TradeJournalPatchedTailProbe {
    public static void main(String[] args) throws Exception {
        if (args.length != 2) throw new IllegalArgumentException("isolated journal root and partition required");
        File root = new File(args[0]);
        if (!root.isDirectory() || !new File(root, args[1]).isDirectory())
            throw new IllegalArgumentException("missing isolated journal copy");
        if (!args[1].matches("P[0-9]{3}"))
            throw new IllegalArgumentException("invalid partition");
        try (TradePartitionJournal journal = new TradePartitionJournal(root)) {
            System.out.println("PATCHED_TRADE_JOURNAL_LOGICAL_TAIL partition=" + args[1]
                    + " lastSeq=" + journal.lastSeq(args[1])
                    + " SOURCE_COMMIT_AUTHENTICATION=NOT_CHECKED"
                    + " RECOVERY_AUTHORIZED=false");
        }
    }
}
