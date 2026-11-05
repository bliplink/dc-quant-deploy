package com.app.common.replication;

import java.nio.file.*;
import java.security.*;
import java.security.spec.X509EncodedKeySpec;
import java.util.*;

/** T488 fresh original Common physical voter RSA and zero ACK WAL quorum seal.
 * Call on Docker-managed native volume only, after ALL four node-local births.
 * Never issues synthetic signatures or makes a ZK partition READY. */
public final class T488OriginalE1DualPhysicalGenesisSeal {
    public static void main(String[] args) throws Exception {
        if (args.length != 2) throw new IllegalArgumentException("bornRoot trustedPublicDir");
        Path root = Paths.get(args[0]).toAbsolutePath().normalize();
        Path pins = Paths.get(args[1]).toAbsolutePath().normalize();
        if (!root.toString().equals("/srv/dc/data/t488-born") || Files.isSymbolicLink(root))
            throw new IllegalArgumentException("T488 requires dedicated native Docker birth root");
        KeyFactory keys = KeyFactory.getInstance("RSA");
        PublicKey a = keys.generatePublic(new X509EncodedKeySpec(
                Files.readAllBytes(pins.resolve("CommonHaDemoA.pub.der"))));
        PublicKey b = keys.generatePublic(new X509EncodedKeySpec(
                Files.readAllBytes(pins.resolve("CommonHaDemoB.pub.der"))));
        if (Arrays.equals(a.getEncoded(), b.getEncoded()))
            throw new IllegalStateException("not two independent original RSA voters");
        // Preflight BOTH services completely before mutating any seal.
        for (int phase = 0; phase < 2; phase++) {
            for (String service : new String[]{"OrderSvr", "TradeSvr"}) {
                String nodeA = service + "A", nodeB = service + "B";
                String ns = "/otc/t488-fresh-20261105-r1/"
                        + ("OrderSvr".equals(service) ? "order" : "trade");
                Path serviceRoot = root.resolve(service);
                int completed = 0;
                for (int i = 0; i < 256; i++) {
                    String id = String.format(Locale.ROOT, "P%03d", i);
                    String primary = i < 128 ? nodeA : nodeB;
                    DurableWalCommitQuorum.Membership members =
                            new DurableWalCommitQuorum.Membership(
                                    service, id, primary, 1, 1, Arrays.asList(
                                    new DurableWalCommitQuorum.Member(nodeA, "MacDockerSlotA", a),
                                    new DurableWalCommitQuorum.Member(nodeB, "MacDockerSlotB", b)));
                    Path first = serviceRoot.resolve(nodeA).resolve(id);
                    Path second = serviceRoot.resolve(nodeB).resolve(id);
                    byte[] imageA = new CommonDurableGenesisVoterImage(
                            first.resolve("node-voter"), members, nodeA).readCertifiedLocalImage();
                    byte[] imageB = new CommonDurableGenesisVoterImage(
                            second.resolve("node-voter"), members, nodeB).readCertifiedLocalImage();
                    if (!MessageDigest.isEqual(imageA, imageB))
                        throw new IllegalStateException("original A/B image differs " + service + "/" + id);
                    String hash = SnapshotTransferIntegrity.sha256(imageA);
                    CommonCertifiedGenesisQuorum.Receipt receiptA =
                            CommonCertifiedGenesisQuorum.Receipt.fromWire(nodeA, hash,
                                    Files.readAllBytes(first.resolve("receipts")
                                    .resolve(nodeA + ".rsa2048")));
                    CommonCertifiedGenesisQuorum.Receipt receiptB =
                            CommonCertifiedGenesisQuorum.Receipt.fromWire(nodeB, hash,
                                    Files.readAllBytes(second.resolve("receipts")
                                    .resolve(nodeB + ".rsa2048")));
                    List<CommonCertifiedGenesisQuorum.Receipt> receipts =
                            Arrays.asList(receiptA, receiptB);
                    CommonCertifiedGenesisQuorum.verify(members, imageA, receipts);
                    Map<String, Path> originalWal = new LinkedHashMap<>();
                    originalWal.put(nodeA, serviceRoot.resolve(nodeA)
                            .resolve("original-wal").resolve(id));
                    originalWal.put(nodeB, serviceRoot.resolve(nodeB)
                            .resolve("original-wal").resolve(id));
                    CommonOriginalE1ZeroAckBirthEvidence zero =
                            new CommonOriginalE1ZeroAckBirthEvidence(ns, hash, originalWal);
                    zero.requireOriginalPhysicalZeroAckWal(members, members.members.get(nodeA));
                    zero.requireOriginalPhysicalZeroAckWal(members, members.members.get(nodeB));
                    Path target = serviceRoot.resolve("sealed").resolve(id);
                    if (Files.exists(target))
                        throw new IllegalStateException("never overwrite original signed seal: " + service + "/" + id);
                    if (phase == 1) {
                        CommonCertifiedGenesisQuorum.Verified result =
                                CommonCertifiedGenesisQuorum.sealAndVerify(target, members, imageA, receipts);
                        if (!hash.equals(result.originalSha256))
                            throw new IllegalStateException("signed seal changed original image");
                        completed++;
                    }
                }
                System.out.println("T488_ORIGINAL_E1_DUAL_RSA_PASS service=" + service
                        + " phase=" + phase + " partitions=" + (phase == 1 ? completed : 256)
                        + " READY=false");
            }
        }
    }
}