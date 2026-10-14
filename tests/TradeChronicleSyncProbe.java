import java.io.File;
import java.nio.file.Files;
import net.openhft.chronicle.queue.ChronicleQueue;
import net.openhft.chronicle.queue.ExcerptAppender;
import net.openhft.chronicle.queue.impl.single.SingleChronicleQueueBuilder;
import net.openhft.chronicle.bytes.Bytes;
import net.openhft.chronicle.bytes.MappedBytesStore;
import net.openhft.chronicle.bytes.SyncMode;
/** Temporary isolated queue write/msync API validation; never use live WAL. */
public final class TradeChronicleSyncProbe {
    public static void main(String[] args) throws Exception {
        File path=Files.createTempDirectory("trade-commit-msync-api").toFile();
        try (ChronicleQueue q=SingleChronicleQueueBuilder.single(path).build()) {
            ExcerptAppender appender=q.acquireAppender();
            String value="c2VjdXJl\t3\t100\tU1RBVEU=\tZXY=\t123\te30=";
            for(int i=0;i<20;i++) appender.writeText(value+i);
            Bytes<?> bytes=appender.wire().bytes();
            System.out.println("WAL_BYTES_CLASS="+bytes.getClass().getName()
                +" MAPPED_STORE="+bytes.bytesStore().getClass().getName()
                +" WRITE_POSITION="+bytes.writePosition());
            if(!(bytes.bytesStore() instanceof MappedBytesStore))
                throw new IllegalStateException("no mapped WAL storage");
            long started=System.nanoTime();
            ((MappedBytesStore)bytes.bytesStore()).syncUpTo(bytes.writePosition(),SyncMode.SYNC);
            long micros=(System.nanoTime()-started)/1000L;
            System.out.println("EXPLICIT_COMMIT_MSYNC_CALLED elapsedMicros="+micros
                +" result=NO_CRASH_DURABILITY_CLAIM");
            final long[] alternate = new long[1];
            final Throwable[] failure = new Throwable[1];
            Thread snapshotThread = new Thread(() -> {
                try {
                    ExcerptAppender schedulerAppender = q.acquireAppender();
                    Bytes<?> current = schedulerAppender.wire().bytes();
                    alternate[0] = current.writePosition();
                    if (!(current.bytesStore() instanceof MappedBytesStore))
                        throw new IllegalStateException("scheduler thread lacks mapped WAL");
                    ((MappedBytesStore)current.bytesStore()).syncUpTo(current.writePosition(), SyncMode.SYNC);
                } catch(Throwable error) { failure[0] = error; }
            });
            snapshotThread.start();
            snapshotThread.join(10000);
            if(snapshotThread.isAlive()) throw new IllegalStateException("scheduler thread stuck");
            System.out.println("SNAPSHOT_THREAD_APPENDER_SYNC="+(failure[0]==null?"OK":"FAILED")
                    +" threadWritePosition="+alternate[0]+" sourcePosition="+bytes.writePosition()
                    +" error="+(failure[0]==null?"none":failure[0].toString()));
            if(failure[0]!=null) throw new IllegalStateException("scheduler thread sync failed",failure[0]);
            final long tailIndex = appender.lastIndexAppended();
            final long[] tailReadPosition = new long[1];
            final Throwable[] tailFailure = new Throwable[1];
            Thread tailerThread = new Thread(() -> {
                try {
                    net.openhft.chronicle.queue.ExcerptTailer reader = q.createTailer();
                    if (!reader.moveToIndex(tailIndex))
                        throw new IllegalStateException("true tail index not movable");
                    try (net.openhft.chronicle.wire.DocumentContext document =
                            reader.readingDocument()) {
                        if (!document.isPresent())
                            throw new IllegalStateException("true tail has no document");
                        Bytes<?> mapping = document.wire().bytes();
                        tailReadPosition[0] = mapping.readLimit();
                        if (!(mapping.bytesStore() instanceof MappedBytesStore))
                            throw new IllegalStateException("tailer lacks mapped WAL");
                        ((MappedBytesStore)mapping.bytesStore()).syncUpTo(mapping.readLimit(), SyncMode.SYNC);
                    }
                } catch(Throwable error) { tailFailure[0] = error; }
            });
            tailerThread.start();
            tailerThread.join(10000);
            if(tailerThread.isAlive()) throw new IllegalStateException("tailer thread stuck");
            System.out.println("SNAPSHOT_THREAD_TAILER_SYNC="+(tailFailure[0]==null?"OK":"FAILED")
                +" readPosition="+tailReadPosition[0]+" sourcePosition="+bytes.writePosition()
                +" error="+(tailFailure[0]==null?"none":tailFailure[0].toString()));
            if(tailFailure[0]!=null) throw new IllegalStateException("tailer sync failed",tailFailure[0]);
        } finally {
            for (File entry : path.listFiles()) {
                if(entry.isFile()&&!entry.delete()) throw new Exception("failed remove temp file");
            }
            if(!path.delete()) throw new Exception("failed remove temp dir");
        }
    }
}
