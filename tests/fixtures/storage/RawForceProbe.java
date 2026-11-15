import java.nio.*;
import java.nio.channels.*;
import java.nio.file.*;
import java.util.*;
public final class RawForceProbe {
 static final byte[] PAYLOAD=new byte[4096];
 static void append(FileChannel file,int commands)throws Exception {
  for(int n=0;n<commands;n++){ByteBuffer b=ByteBuffer.wrap(PAYLOAD);while(b.hasRemaining())file.write(b);}
  file.force(true);
 }
 static void report(String name,long[] elapsed,int commands){
  Arrays.sort(elapsed);double total=0;for(long n:elapsed)total+=n;
  System.out.printf(Locale.ROOT,"{\"scenario\":\"%s\",\"synthetic_io_only_no_signing_or_network_or_ack\":true,\"commands_per_sample\":%d,\"samples\":%d,\"mean_ms\":%.6f,\"p50_ms\":%.6f,\"p99_ms\":%.6f,\"max_ms\":%.6f}%n",name,commands,elapsed.length,total/elapsed.length/1e6,elapsed[elapsed.length/2]/1e6,elapsed[(int)Math.ceil(elapsed.length*.99)-1]/1e6,elapsed[elapsed.length-1]/1e6);
 }
 public static void main(String[] args)throws Exception {
  Path root=Paths.get(args[0]);if(!root.isAbsolute())throw new IllegalArgumentException();
  for(int group:new int[]{1,64}){
   for(int barriers:new int[]{1,4}){
    int count=group==1?500:100;long[] elapsed=new long[count];FileChannel[] files=new FileChannel[barriers];
    try{
     for(int f=0;f<barriers;f++)files[f]=FileChannel.open(root.resolve("force-"+group+"-"+barriers+"-"+f),StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE);
     for(int n=-50;n<count;n++){
      long begun=System.nanoTime();for(FileChannel file:files)append(file,group);
      if(n>=0)elapsed[n]=System.nanoTime()-begun;
     }
    }finally{for(FileChannel file:files)if(file!=null)file.close();}
    report("append-force-"+barriers+"-barriers",elapsed,group);
   }
  }
  long[] elapsed=new long[500];
  try(FileChannel wal=FileChannel.open(root.resolve("local-wal"),StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE);FileChannel dir=FileChannel.open(root,StandardOpenOption.READ)){
   for(int n=-50;n<elapsed.length;n++){
    long begun=System.nanoTime();append(wal,1);Path pending=root.resolve("head.pending");
    try(FileChannel head=FileChannel.open(pending,StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE)){append(head,1);}
    Files.move(pending,root.resolve("head"),StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);dir.force(true);
    if(n>=0)elapsed[n]=System.nanoTime()-begun;
   }
  }
  report("local-wal-head-rename-directory",elapsed,1);
 }
}
