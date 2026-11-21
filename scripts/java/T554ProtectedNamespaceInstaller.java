import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Locale;
import java.util.Properties;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.apache.zookeeper.CreateMode;
import org.apache.zookeeper.KeeperException;
import org.apache.zookeeper.Op;
import org.apache.zookeeper.Watcher;
import org.apache.zookeeper.ZooDefs;
import org.apache.zookeeper.ZooKeeper;
import org.apache.zookeeper.data.ACL;
import org.apache.zookeeper.data.Id;
import org.apache.zookeeper.data.Stat;
import org.apache.zookeeper.server.auth.DigestAuthenticationProvider;

/** Fresh Mac Demo installation only. Creates two non-routable E1 manifests. */
public final class T554ProtectedNamespaceInstaller {
    private static final List<String> SERVICES = Arrays.asList("order", "trade");

    private static final class Session extends ZooKeeper implements AutoCloseable {
        Session(String hosts, Watcher listener) throws java.io.IOException {
            super(hosts, 10000, listener);
        }
    }

    private static Session connect(String hosts) throws Exception {
        CountDownLatch connected = new CountDownLatch(1);
        Session zk = new Session(hosts, event -> {
            if (event.getState() == Watcher.Event.KeeperState.SyncConnected) connected.countDown();
        });
        if (!connected.await(15, TimeUnit.SECONDS)) {
            zk.close();
            throw new IllegalStateException("ZooKeeper quorum is unavailable");
        }
        return zk;
    }

    private static String credential(Properties keys, String name) {
        String secret = keys.getProperty(name);
        if (secret == null || !secret.matches("[0-9a-f]{64}")) throw new IllegalArgumentException("missing install identity");
        return "t554-" + name + ":" + secret;
    }

    private static List<ACL> permissions(String writer) throws Exception {
        // Existing status clients read routes and membership. Only the scoped
        // controller can change data, grant permissions, create or remove children.
        List<ACL> acl = new ArrayList<>(ZooDefs.Ids.READ_ACL_UNSAFE);
        acl.add(new ACL(ZooDefs.Perms.ALL, new Id("digest", DigestAuthenticationProvider.generateDigest(writer))));
        return acl;
    }

    private static byte[] original(String kind, String file) throws Exception {
        String service = kind.equals("order") ? "OrderSvr" : "TradeSvr";
        byte[] data = Files.readAllBytes(Paths.get(file));
        StringBuilder expected = new StringBuilder("NPC1|1");
        for (int i=0; i<256; i++) {
            expected.append(String.format(Locale.ROOT, "\nP%03d|1|%s%s|%s%s|STRICT_QUORUM|RECOVERING",
                    i,service,i<128?"A":"B",service,i<128?"B":"A"));
        }
        if (!Arrays.equals(data, expected.toString().getBytes(StandardCharsets.UTF_8)))
            throw new IllegalArgumentException("fresh original E1 manifest changed for " + kind);
        return data;
    }

    private static void requireDenied(ZooKeeper session, String manifest) throws Exception {
        // The fresh manifest is version zero. This comparison cannot mutate
        // data even if a mistakenly permissive ACL lets the request through.
        try {
            session.setData(manifest, new byte[0], Integer.MAX_VALUE);
            throw new IllegalStateException("unexpected write to a fresh manifest");
        } catch (KeeperException.NoAuthException denied) {
            return;
        } catch (KeeperException.BadVersionException open) {
            throw new IllegalStateException("control mutation permission was granted");
        }
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 5 || !args[1].matches("/otc/mac-demo-[0-9]{8}-[0-9]{6}"))
            throw new IllegalArgumentException("fresh T554 namespace and credential file required");
        String hosts=args[0], root=args[1];
        Properties secrets=new Properties();
        try (java.io.InputStream in=Files.newInputStream(Paths.get(args[2]))) { secrets.load(in); }
        byte[][] birth={original("order",args[3]),original("trade",args[4])};
        try (Session install=connect(hosts); Session anonymous=connect(hosts)) {
            String admin=credential(secrets,"bootstrap");
            install.addAuthInfo("digest",admin.getBytes(StandardCharsets.UTF_8));
            if (install.exists(root,false)!=null) throw new IllegalStateException("refusing existing Demo namespace");
            if (install.exists("/otc",false)==null) {
                try { install.create("/otc",new byte[0],ZooDefs.Ids.OPEN_ACL_UNSAFE,CreateMode.PERSISTENT); }
                catch (KeeperException.NodeExistsException alreadyCreated) { /* Shared root already exists. */ }
            }
            List<Op> updates=new ArrayList<>();
            updates.add(Op.create(root,new byte[0],permissions(admin),CreateMode.PERSISTENT));
            for (int i=0;i<SERVICES.size();i++) {
                String kind=SERVICES.get(i), scope=root+"/"+kind;
                List<ACL> acl=permissions(credential(secrets,kind));
                // ZooKeeper validates create ACLs in the transaction using the
                // session's authenticated identities for these parent nodes.
                install.addAuthInfo("digest",credential(secrets,kind).getBytes(StandardCharsets.UTF_8));
                updates.add(Op.create(scope,new byte[0],acl,CreateMode.PERSISTENT));
                updates.add(Op.create(scope+"/leases",new byte[0],acl,CreateMode.PERSISTENT));
                updates.add(Op.create(scope+"/manifest",birth[i],acl,CreateMode.PERSISTENT));
            }
            install.multi(updates);
            for (int i=0;i<SERVICES.size();i++) {
                String kind=SERVICES.get(i), path=root+"/"+kind+"/manifest";
                try (Session writer=connect(hosts); Session reader=connect(hosts)) {
                    writer.addAuthInfo("digest",credential(secrets,kind).getBytes(StandardCharsets.UTF_8));
                    reader.addAuthInfo("digest",credential(secrets,kind+"-reader").getBytes(StandardCharsets.UTF_8));
                    requireDenied(anonymous,path);
                    requireDenied(reader,path);
                    requireDenied(writer,root+"/"+SERVICES.get(1-i)+"/manifest");
                    Stat stat=new Stat();
                    byte[] actual=writer.getData(path,false,stat);
                    if (stat.getVersion()!=0 ||stat.getAversion()!=0 ||!Arrays.equals(actual,birth[i]))
                        throw new IllegalStateException("original protected E1 readback differs");
                    List<ACL> expected=permissions(credential(secrets,kind));
                    for (String node:Arrays.asList(root+"/"+kind,root+"/"+kind+"/leases",path)) {
                        List<ACL> acl=writer.getACL(node,new Stat());
                        if (acl.size()!=expected.size() ||!acl.containsAll(expected))
                            throw new IllegalStateException("control ACL differs from provisioned writer");
                    }
                    System.out.println("T554_PROTECTED_COMMON_ORIGIN "+kind+" "+stat.getCzxid());
                }
            }
        } finally { secrets.clear(); }
    }
}
