package com.opentradingcore.demo;

import com.app.common.partition.PartitionAssignment;
import com.app.common.partition.PartitionFailoverController;
import com.app.common.partition.ZkPartitionFailoverControlPlane;
import com.app.common.partition.ZkPartitionFailoverRuntime;
import com.app.common.zk.ZookeeperClient;
import org.apache.zookeeper.CreateMode;
import org.I0Itec.zkclient.exception.ZkNodeExistsException;
import java.util.Arrays;
import java.io.IOException;
import java.util.Map;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;
import org.apache.zookeeper.data.Stat;
import com.gateway.connector.utils.JsonUtils;

/**
 * Isolated v19 RF2 automatic failover STAGING ONLY. This can CAS a new
 * non-routable RECOVERING epoch but NEVER reconfigure strict 2/2 ACK or grant
 * data-plane READY. This is deliberately disabled without explicit opt-in.
 */
final class DemoV19Rf2AutoStage implements AutoCloseable {
    private static final String ROOT=DemoZkFenceSource.ISOLATED_ROOT+"/harness";
    private static final String MEMBERS=ROOT+"/members";
    private static final String ASSIGN=ROOT+"/assignments";
    private static final String LEASE=ROOT+"/rf2-auto-stage-controller";
    private final String node;
    private final ZkPartitionFailoverControlPlane plane;
    private final ZkPartitionFailoverRuntime runtime;
    private final ZookeeperClient zk;
    private final DemoV19DurableRuntime durable;
    private final DemoV19Rf2LearnerCatchup learner;
    private final DemoV19Rf2StrictRejoinPreflight strictPreflight;
    private final DemoV19Rf2StrictCutoverCoordinator strictCutover;
    private final DemoV19Rf2StrictFailoverEvidence strictSurvivor;
    private volatile int strictCutoverPhase=0;
    private volatile long lastStrictActivatedEpoch=0;
    private volatile String lastPreflightFingerprint="";
    private volatile String lastPreflightFailure="";
    private final ScheduledExecutorService autoDegrade=Executors.newSingleThreadScheduledExecutor(r->{
        Thread t=new Thread(r,"v19-rf2-auto-degrade"); t.setDaemon(true); return t;
    });
    private final AtomicLong earliestActivationNs=new AtomicLong(
            System.nanoTime()+TimeUnit.SECONDS.toNanos(5));

    static boolean enabled() {
        return "1".equals(System.getenv("DEMO_V19_RF2_AUTO_STAGE"))
                && "1".equals(System.getenv("DEMO_V19_RF2_SHARD_PILOT"))
                && "0".equals(System.getenv("DEMO_V19_THREE_DATA_NODES"))
                && "1".equals(System.getenv("DEMO_V19_CUSTODY_ACK_PILOT"));
    }

    DemoV19Rf2AutoStage(ZookeeperClient zk, String node,
            DemoV19DurableRuntime durable,DemoJournalCatalog catalog,
            DemoV19Rf2DynamicReceiptService sharedSigner) {
        if (!enabled() || zk==null || durable==null
                || (!"CommonHaDemoA".equals(node) && !"CommonHaDemoB".equals(node)))
            throw new IllegalArgumentException("isolated RF2 auto-stage requires live custody quorum");
        this.node=node;
        this.zk=zk;
        this.durable=durable;
        // ZK ephemeral node is session-owned by the actual DATA JVM, not an
        // external script or a TCP health probe that might misclassify a pause.
        ensureRoot(zk,MEMBERS);
        for (String member : Arrays.asList("CommonHaDemoA","CommonHaDemoB"))
            ensureRoot(zk,MEMBERS+"/"+member);
        String presence=MEMBERS+"/"+node+"/"+node;
        try { zk.create(presence,node,CreateMode.EPHEMERAL); }
        catch (ZkNodeExistsException alreadyExists) {
            throw new IllegalStateException("duplicate live data identity: "+node,alreadyExists);
        }
        plane=new ZkPartitionFailoverControlPlane(zk,ASSIGN,MEMBERS,LEASE,node);
        strictSurvivor="1".equals(System.getenv("DEMO_V19_RF2_DYNAMIC_STRICT_ACK"))
                ? new DemoV19Rf2StrictFailoverEvidence(
                    zk,catalog,java.util.Objects.requireNonNull(sharedSigner,
                        "one physical custody signer shared with the data JVM")) : null;
        strictCutover="1".equals(System.getenv("DEMO_V19_RF2_STRICT_CUTOVER_EXPERIMENT"))
                ? new DemoV19Rf2StrictCutoverCoordinator(zk,plane,node) : null;
        strictPreflight="1".equals(System.getenv("DEMO_V19_RF2_STRICT_REJOIN_PREFLIGHT"))
                ? new DemoV19Rf2StrictRejoinPreflight(zk,plane,node) : null;
        learner="1".equals(System.getenv("DEMO_V19_RF2_AUTO_LEARNER"))
                && ("CommonHaDemoA".equals(node) || "CommonHaDemoB".equals(node))
                ? new DemoV19Rf2LearnerCatchup(node,plane,catalog) : null;
        runtime=new ZkPartitionFailoverRuntime(plane,
                (current,candidate,replicas)->{
                    if (!node.equals(candidate)
                            || !"P000".equals(current.getPartitionId())
                            || current.replicaNodes().size()!=1
                            || current.getEpoch()!=1
                            || replicas.size()!=1 || !node.equals(replicas.get(0)))
                        throw new IllegalStateException("unsupported RF2 candidate or old membership");
                    try { durable.requireCertifiedOldRf2Survivor(current); }
                    catch (Exception denied) {
                        throw new IllegalStateException("old ACK frontier not certified",denied);
                    }
                },Arrays.asList("CommonHaDemoA","CommonHaDemoB"),
                1,500L,new ZkPartitionFailoverRuntime.Listener() {
                    @Override public void onResult(PartitionFailoverController.Result r) {
                        if (r.getOutcome()==PartitionFailoverController.Outcome.APPLIED_NOT_READY) {
                            earliestActivationNs.set(System.nanoTime()+TimeUnit.SECONDS.toNanos(5));
                            System.out.println("V19_RF2_AUTO_STAGED partition="+r.getPartitionId()
                                +" old="+r.getPreviousPrimary()
                                +" candidate="+r.getNewPrimary()
                                +" newEpoch="+r.getNewEpoch()
                                +" state=RECOVERING writeAdmission=DENIED");
                        }
                    }
                    @Override public void onFailure(String partition,RuntimeException failure) {
                        System.err.println("V19_RF2_AUTO_STAGE_FAILED partition="+partition
                                +" type="+failure.getClass().getSimpleName());
                    }
                });
    }

    void start() {
        runtime.start();
        // Explicit NEW-TEST-INSTANCE-ONLY experiment. Never enabled in the
        // established v19 Demo or production. Stops at fsynced strict Genesis:
        // strict READY and client ACK deliberately remain CLOSED.
        if (strictCutover!=null) autoDegrade.scheduleWithFixedDelay(()->{
            try {
                // The six independently checked control phases may advance
                // immediately when each stage has succeeded. A 3-second
                // scheduler sleep between every stage needlessly delayed
                // recovery by at least 15 seconds.
                for(int i=0;i<6;i++) {
                    int previous=strictCutoverPhase;
                    if(strictCutoverPhase==0 && strictCutover.resumePreparedGenesis())
                        strictCutoverPhase=3;
                    else if(strictCutoverPhase==0 && strictCutover.freeze())
                        strictCutoverPhase=1;
                    else if(strictCutoverPhase==1 && strictCutover.prepareGenesis())
                        strictCutoverPhase=2;
                    else if(strictCutoverPhase==2 && strictCutover.certifyGenesis()>0)
                        strictCutoverPhase=3;
                    else if(strictCutoverPhase==3 && strictCutover.custodyGenesis()>0)
                        strictCutoverPhase=4;
                    else if(strictCutoverPhase==4
                            && strictCutover.verifyTwoPhysicalCustodyHeads()>0)
                        strictCutoverPhase=5;
                    else if(strictCutoverPhase==5 && strictCutover.activateStrictReady()){
                        lastStrictActivatedEpoch=strictCutover.currentActiveStrictEpoch();
                        strictCutoverPhase=6;
                    } else if(strictCutoverPhase==6 &&
                            strictCutover.readyForAnotherUpgrade(lastStrictActivatedEpoch)){
                        System.out.println("V19_RF2_STRICT_CUTOVER_REARMED oldStrictEpoch="
                                +lastStrictActivatedEpoch+" newDegradedEpoch="
                                +(lastStrictActivatedEpoch+1));
                        strictCutoverPhase=0;
                    }
                    // Never skip an incomplete/failed phase, or begin another
                    // epoch during the same tick. Every step retains the
                    // coordinator's ZK CAS, fencing, WAL and custody checks.
                    if(strictCutoverPhase==previous || strictCutoverPhase==0
                            || strictCutoverPhase==6)break;
                }
            } catch(Exception notYet) {
                System.err.println("V19_RF2_STRICT_CUTOVER_PENDING phase="+strictCutoverPhase
                        +" reason="+notYet.getClass().getSimpleName()+": "+notYet.getMessage());
            }
        },1,1,TimeUnit.SECONDS);
        // Read-only, independently authenticated readiness observation;
        // it is NOT permission to reconfigure membership or ACK strict 2/2.
        if (strictPreflight!=null) autoDegrade.scheduleWithFixedDelay(()->{
            try {
                DemoV19Rf2StrictRejoinPreflight.Evidence candidate=strictPreflight.once();
                lastPreflightFailure="";
                String fingerprint=candidate.summary();
                if (!fingerprint.equals(lastPreflightFingerprint)) {
                    lastPreflightFingerprint=fingerprint;
                    System.out.println("V19_RF2_STRICT_REJOIN_PREFLIGHT_MATCH "+fingerprint
                            +" eligibleForStrictCutover=false actualStrict2of2Ack=false");
                }
            } catch (Exception denied) {
                // Keep degrade ACK live. Never open strict readiness on failure.
                if(!lastPreflightFingerprint.isEmpty())lastPreflightFingerprint="";
                String reason=denied.getClass().getSimpleName()+": "+denied.getMessage();
                if(!reason.equals(lastPreflightFailure)) {
                    lastPreflightFailure=reason;
                    System.err.println("V19_RF2_STRICT_REJOIN_PREFLIGHT_DENIED "+reason);
                }
            }
        },4,12,TimeUnit.SECONDS);
        if (learner!=null) autoDegrade.scheduleWithFixedDelay(()->{
            try {
                if (learner.once()) System.out.println(
                        "V19_RF2_LEARNER_CAUGHT_UP learner="+node);
            } catch (Exception denied) {
                System.err.println("V19_RF2_LEARNER_CATCHUP_DELAYED reason="
                        +denied.getClass().getSimpleName()+": "+denied.getMessage());
            }
        },3,3,TimeUnit.SECONDS);
        if ("1".equals(System.getenv("DEMO_V19_RF2_AUTO_DEGRADE"))) {
            autoDegrade.scheduleWithFixedDelay(()->{
                try {
                    tryStageDegradedFromStrictReady();
                    tryStageEpoch3AfterBDeath();
                    tryPublishDegradedReady();
                }
                catch (Exception unsafe) {
                    System.err.println("V19_RF2_DEGRADE_NOT_READY reason="
                            +unsafe.getClass().getSimpleName()+": "+unsafe.getMessage());
                }
            }, 1,1,TimeUnit.SECONDS);
        }
    }

    /** An independently certified RF2 2/2 group may degrade to a NEW solo
     * epoch when either data voter dies. The survivor must hold the latest
     * cryptographically valid custody HEAD on its own fsynced WAL.
     * The ZK CAS installs RECOVERING and revokes the entire OLD strict epoch.
     */
    private void tryStageDegradedFromStrictReady()throws Exception {
        if(strictSurvivor==null || !plane.isConnected())return;
        PartitionFailoverController.VersionedAssignment v=plane.read("P000");
        if(v==null)return;
        PartitionAssignment old=v.getAssignment();
        if(!old.isRoutable() || old.getEpoch()<2 || old.getEpoch()>=DemoV19Rf2EpochLimits.MAX_EPOCH
                || old.replicaNodes().size()!=1)return;
        String oldPrimary=old.getPrimary(),oldReplica=old.replicaNodes().get(0);
        if(!node.equals(oldPrimary) && !node.equals(oldReplica))return;
        String failed=node.equals(oldPrimary)?oldReplica:oldPrimary;
        if(plane.isLive(failed) || !plane.isLive(node))return;
        if(!plane.hasLease() && !plane.tryAcquireLease())return;
        Stat stat=new Stat();String path=ASSIGN+"/P000";
        Object raw=zk.readData(path,stat);
        if(raw==null || stat.getVersion()!=v.getVersion())return;
        @SuppressWarnings("unchecked") Map<String,Object> record=
            JsonUtils.Deserialize(String.valueOf(raw),Map.class);
        if(record==null || !"READY".equals(record.get("state"))
                || !"QUORUM_DURABLE".equals(record.get("durabilityPolicy"))
                || !Boolean.TRUE.equals(record.get("quorumDurable"))
                || !oldPrimary.equals(record.get("primary"))
                || !java.util.Collections.singletonList(oldReplica).equals(record.get("replicas"))
                || !(record.get("epoch") instanceof Number)
                || ((Number)record.get("epoch")).longValue()!=old.getEpoch())
            return;
        DemoV19Rf2StrictFailoverEvidence.Proof proof=
            strictSurvivor.fromStrictReady(record,node);
        if(!plane.isConnected() || !plane.hasLease()
                || !plane.isLive(node) || plane.isLive(failed))return;
        record.put("strictRecoveryOldPrimary",oldPrimary);
        record.put("strictRecoveryOldEpoch",proof.epoch);
        record.put("strictRecoveryConfigVersion",proof.config);
        record.put("strictRecoveryCertifiedSeq",proof.seq);
        record.put("strictRecoveryCertifiedSha",proof.sha);
        record.put("strictOldEpochWasQuorumDurable",true);
        record.put("primary",node);
        record.put("epoch",old.getEpoch()+1);
        record.put("assignmentVersion",old.getAssignmentVersion()+1);
        record.put("state","RECOVERING");
        record.put("replica",null);
        record.put("replicas",java.util.Collections.emptyList());
        record.put("learners",java.util.Collections.singletonList(failed));
        record.put("durabilityPolicy","AUTO_DEGRADED_LOCAL_DURABLE");
        record.put("quorumDurable",false);
        record.remove("strictTransition");
        try{zk.writeDataReturnStat(path,JsonUtils.Serializer(record),stat.getVersion());}
        catch(org.I0Itec.zkclient.exception.ZkBadVersionException changed){return;}
        earliestActivationNs.set(System.nanoTime()+TimeUnit.SECONDS.toNanos(5));
        System.out.println("V19_RF2_STRICT_TO_LOCAL_AUTO_STAGED old="+oldPrimary
            +" survivor="+node+" epoch="+(old.getEpoch()+1)
            +" certifiedSeq="+proof.seq+" state=RECOVERING quorumDurable=false");
    }

    /** True automatic B->A fallback: A was a durable Learner but may lag
     * B's solo ACK tail. We only claim the old RF2 certified prefix, fence B
     * through ZK and EXPLICITLY retain the non-zero RPO local-ACK policy.
     * A RECOVERING CAS is never client writable until the old lease expires.
     */
    private void tryStageEpoch3AfterBDeath() throws Exception {
        if (!"1".equals(System.getenv("DEMO_V19_RF2_AUTO_DEGRADE"))
                || !plane.isConnected()) return;
        // Only an actually eligible failover candidate may take the control
        // lease. A healthy learner must not monopolize strict rejoin control.
        PartitionFailoverController.VersionedAssignment versioned=plane.read("P000");
        if (versioned==null) return;
        PartitionAssignment old=versioned.getAssignment();
        if (old.getEpoch()<2 || old.getEpoch()>=DemoV19Rf2EpochLimits.MAX_EPOCH
                || !"READY".equals(old.getState())
                || node.equals(old.getPrimary())
                || !old.replicaNodes().isEmpty() || !old.isLearner(node)
                || plane.isLive(old.getPrimary())) return;
        if (!plane.hasLease() && !plane.tryAcquireLease()) return;
        long retained=durable.requireSafeEpoch3OldLearner(old);
        String path=ASSIGN+"/P000";
        Stat stat=new Stat();Object raw=zk.readData(path,stat);
        if (raw==null || stat.getVersion()!=versioned.getVersion()) return;
        @SuppressWarnings("unchecked") Map<String,Object> record=
                JsonUtils.Deserialize(String.valueOf(raw),Map.class);
        if (record==null || !old.getPrimary().equals(record.get("primary"))
                || !"READY".equals(record.get("state"))
                || !(record.get("epoch") instanceof Number)
                || ((Number)record.get("epoch")).longValue()!=old.getEpoch()
                || !"AUTO_DEGRADED_LOCAL_DURABLE".equals(record.get("durabilityPolicy"))
                || !Boolean.FALSE.equals(record.get("quorumDurable"))) return;
        if (!plane.isConnected() || !plane.hasLease()
                || plane.isLive(old.getPrimary())) return;
        record.put("primary",node);
        record.put("epoch",old.getEpoch()+1);
        record.put("assignmentVersion",old.getAssignmentVersion()+1);
        record.put("state","RECOVERING");
        record.put("replica",null);
        record.put("replicas",java.util.Collections.emptyList());
        record.put("learners",java.util.Collections.singletonList(old.getPrimary()));
        record.put("previousEpochMayHaveUnreplicatedAcks",true);
        record.put("candidateDurableSeqAtPromotion",retained);
        try { zk.writeDataReturnStat(path,JsonUtils.Serializer(record),stat.getVersion()); }
        catch (org.I0Itec.zkclient.exception.ZkBadVersionException race) { return; }
        earliestActivationNs.set(System.nanoTime()+TimeUnit.SECONDS.toNanos(5));
        System.out.println("V19_RF2_REVERSE_AUTO_STAGED old="+old.getPrimary()
                +" candidate="+node+" epoch="+(old.getEpoch()+1)+" state=RECOVERING"
                +" candidateDurableSeq="+retained+" possibleRpoLoss=true");
    }

    private void tryPublishDegradedReady() throws Exception {
        if (System.nanoTime()<earliestActivationNs.get()
                || !plane.isConnected() || !plane.hasLease() || !plane.isLive(node)) return;
        PartitionFailoverController.VersionedAssignment versioned=plane.read("P000");
        if (versioned==null) return;
        PartitionAssignment current=versioned.getAssignment();
        if (!"P000".equals(current.getPartitionId())
                || (current.getEpoch()<2 || current.getEpoch()>DemoV19Rf2EpochLimits.MAX_EPOCH)
                || !node.equals(current.getPrimary())
                || !"RECOVERING".equals(current.getState())) return;
        long head=current.getEpoch()==2
                ? durable.requireSafeDegradedEpoch2Genesis(current)
                : durable.requireSafeEpoch3Staged(current);
        if (!plane.isConnected() || !plane.hasLease() || !plane.isLive(node)) return;
        String path=ASSIGN+"/P000";
        Stat stat=new Stat();
        Object raw=zk.readData(path,stat);
        if (raw==null || stat.getVersion()!=versioned.getVersion()) return;
        @SuppressWarnings("unchecked") Map<String,Object> record=
                JsonUtils.Deserialize(String.valueOf(raw),Map.class);
        if (record==null || !node.equals(record.get("primary"))
                || !"RECOVERING".equals(record.get("state"))
                || !mayPublishDegradedFromRecovery(record)
                || !(record.get("epoch") instanceof Number)
                || ((Number)record.get("epoch")).longValue()!=current.getEpoch()) return;
        if(Boolean.TRUE.equals(record.get("strictOldEpochWasQuorumDurable"))){
            if(strictSurvivor==null)
                throw new IOException("strict survivor physical proof engine missing");
            DemoV19Rf2StrictFailoverEvidence.Proof proof=
                strictSurvivor.fromStaged(record,node);
            if(proof.seq!=((Number)record.get("strictRecoveryCertifiedSeq")).longValue())
                throw new IOException("strict recovery custody head changed before READY");
        }
        record.put("state","READY");
        record.put("assignmentVersion",current.getAssignmentVersion()+1);
        record.put("durabilityPolicy","AUTO_DEGRADED_LOCAL_DURABLE");
        record.put("quorumDurable",false);
        record.put("degradedFromCertifiedOldEpoch",1);
        record.put("degradedFromCertifiedSeq",head);
        if (!plane.isConnected() || !plane.hasLease()) return;
        try { zk.writeDataReturnStat(path,JsonUtils.Serializer(record),stat.getVersion()); }
        catch (org.I0Itec.zkclient.exception.ZkBadVersionException conflict) { return; }
        System.out.println("V19_RF2_AUTO_DEGRADED_READY partition=P000 primary="+node
                +" epoch="+current.getEpoch()+" oldCertifiedSeq="+head
                +" durability=AUTO_DEGRADED_LOCAL_DURABLE quorumDurable=false");
    }
    /** Strict two-voter auto-rejoin is repeatable only after a genuinely
     * newer, writable SOLO epoch; neither READY 2/2 nor RECOVERING qualify.
     */
    static boolean mayRearmStrictCycle(
            com.app.common.partition.PartitionAssignment current,
            String local,long completedStrictEpoch){
        return current!=null && local!=null
                && completedStrictEpoch>=2
                && current.getEpoch()>completedStrictEpoch
                && current.getEpoch()<DemoV19Rf2EpochLimits.MAX_EPOCH
                && current.isRoutable()
                && local.equals(current.getPrimary())
                && current.replicaNodes().isEmpty()
                && current.getLearners().size()==1
                && !local.equals(current.getLearners().get(0));
    }

    /** Strict cutover FREEZE/GENESIS must NEVER be auto-reopened as a
     * single-node READY just because the candidate's WAL was previously good.
     * Only the legacy failover RECOVERING contract is eligible here.
     */
    static boolean mayPublishDegradedFromRecovery(Map<String,Object> record) {
        return record!=null
                && "RECOVERING".equals(record.get("state"))
                && record.get("strictTransition")==null
                && java.util.Collections.emptyList().equals(record.get("replicas"))
                && (record.get("durabilityPolicy")==null
                    || "AUTO_DEGRADED_LOCAL_DURABLE".equals(record.get("durabilityPolicy")));
    }

    private static void ensureRoot(ZookeeperClient zk,String path) {
        if (zk.exists(path)) return;
        try {zk.create(path,"",CreateMode.PERSISTENT);}
        catch(ZkNodeExistsException concurrent) {
            if (!zk.exists(path)) throw concurrent;
        }
    }
    @Override public void close() {autoDegrade.shutdownNow();runtime.close();}
}
