import java.io.File;
import net.openhft.chronicle.queue.ChronicleQueue;
import net.openhft.chronicle.queue.ExcerptTailer;
import net.openhft.chronicle.queue.TailerDirection;
import net.openhft.chronicle.queue.impl.single.SingleChronicleQueueBuilder;
/** Read-only probe for index-vs-backwards-tail semantics, offline copies only. */
public final class TradeChronicleBackwardIndexProbe {
  public static void main(String[] args) throws Exception {
    if (args.length!=1) throw new IllegalArgumentException("isolated queue copy path");
    try(ChronicleQueue queue=SingleChronicleQueueBuilder.single(new File(args[0])).readOnly(true).build()) {
      ExcerptTailer forward=queue.createTailer();
      long lastPhysicalIndex=-1L;
      long count=0L;
      String body;
      while (true) {
        long before=forward.index();
        body=forward.readText();
        if (body==null) break;
        lastPhysicalIndex=before;
        count++;
      }
      ExcerptTailer back=queue.createTailer().direction(TailerDirection.BACKWARD);
      boolean moved=lastPhysicalIndex >= 0 && back.moveToIndex(lastPhysicalIndex);
      String first=moved?back.readText():null;
      String second=moved?back.readText():null;
      System.out.println("BACKWARD_INDEX_PROBE count="+count+" firstIndex="+queue.firstIndex()+" hintLastIndex="+queue.lastIndex()
        +" truePhysicalLastIndex="+lastPhysicalIndex+" moved="+moved+" reverseSeq1="+parseSeq(first)
        +" reverseSeq2="+parseSeq(second)+" RESTORE_AUTHORIZED=false");
    }
  }
  static String parseSeq(String body) {
    if(body==null)return "null";
    String[] fields=body.split("\\t",-1);
    return fields.length==7?fields[2]:"BAD";
  }
}
