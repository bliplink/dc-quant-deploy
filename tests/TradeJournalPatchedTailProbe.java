import java.io.File;
import com.app.dc.service.cluster.TradePartitionJournal;

/** Forensics only: use on a COPY of a fenced/offline partition, never live WAL. */
public final class TradeJournalPatchedTailProbe {
    public static void main(String[] args) throws Exception {
        if (args.length != 2 && (args.length != 3 || !"--test-msync".equals(args[2])))
            throw new IllegalArgumentException("isolated journal root, partition, optional --test-msync required");
        File root = new File(args[0]);
        if (!root.isDirectory() || !new File(root, args[1]).isDirectory())
            throw new IllegalArgumentException("missing isolated journal copy");
        if (!args[1].matches("P[0-9]{3}"))
            throw new IllegalArgumentException("invalid partition");
        try (TradePartitionJournal journal = new TradePartitionJournal(root)) {
            long lastSeq = journal.lastSeq(args[1]);
            System.out.println("PATCHED_TRADE_JOURNAL_LOGICAL_TAIL partition=" + args[1]
                    + " lastSeq=" + lastSeq
                    + " SOURCE_COMMIT_AUTHENTICATION=NOT_CHECKED"
                    + " RECOVERY_AUTHORIZED=false");
            if (args.length == 3) {
                long start = System.nanoTime();
                journal.syncJournalThrough(args[1], lastSeq);
                System.out.println("ISOLATED_TRADE_WAL_MSYNC partition=" + args[1]
                    + " throughSeq=" + lastSeq
                    + " elapsedMillis=" + ((System.nanoTime() - start) / 1000000L)
                    + " FULL_COMMIT_ACK_PROOF=NOT_CHECKED"
                    + " RESTORE_AUTHORIZED=false");
            }
        }
    }
}
