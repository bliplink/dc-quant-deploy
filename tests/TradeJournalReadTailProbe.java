import java.io.File;
import java.util.List;
import com.app.dc.service.cluster.TradePartitionJournal;
import com.app.dc.service.cluster.TradeJournalRecord;

/** Run ONLY on isolated journal copies; never modifies or authorizes live recovery. */
public final class TradeJournalReadTailProbe {
    public static void main(String[] args) throws Exception {
        if (args.length != 2 || !args[1].matches("P[0-9]{3}"))
            throw new IllegalArgumentException("isolated root and partition required");
        File root = new File(args[0]);
        if (!new File(root, args[1]).isDirectory())
            throw new IllegalArgumentException("missing isolated journal partition");
        try (TradePartitionJournal journal = new TradePartitionJournal(root)) {
            long logicalTail = journal.lastSeq(args[1]);
            List<TradeJournalRecord> tail = journal.readTail(args[1], 4);
            System.out.println("TRADE_READ_TAIL_DIAGNOSTIC partition=" + args[1]
                    + " logicalTail=" + logicalTail
                    + " backwardsCount=" + tail.size()
                    + " backwardNewestSeq=" + (tail.isEmpty() ? -1 : tail.get(0).getSeq())
                    + " backwardOldestSeq=" + (tail.isEmpty() ? -1 : tail.get(tail.size()-1).getSeq())
                    + " ACK_PROOF=NOT_CHECKED"
                    + " RESTORE_AUTHORIZED=false");
        }
    }
}
