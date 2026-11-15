import java.util.*;
import org.junit.runner.*;
import org.junit.runner.notification.*;

/** Test runner only. Production classes must come from the frozen Common JAR. */
public final class QualifiedCommonChecks {
    private static final Set<String> OPTIONAL = new HashSet<>(Arrays.asList(
        "realSignedE5StrictSwappedRolesOnly(com.app.common.replication.CommonCertifiedStrictRecoveryReceiptRoleSwapTest)",
        "twoIndependentOriginalRsaRecoveryReceiptsCannotBeSwappedOrTampered(com.app.common.replication.CommonCertifiedStrictRecoveryReceiptTest)",
        "actualSigkillOnlyCertifiesTwoOfThreePhysicalWalFrames(com.app.common.replication.CommonCertifiedStrictCrashPrefixTest)"));

    public static void main(String[] args) throws Exception {
        if (args.length < 2) throw new IllegalArgumentException("--safety/--classes CLASS... or --method CLASS METHOD");
        Set<String> skipped = new HashSet<>();
        JUnitCore junit = new JUnitCore();
        junit.addListener(new RunListener() {
            @Override public void testAssumptionFailure(Failure failure) {
                skipped.add(failure.getDescription().toString());
            }
            @Override public void testFailure(Failure failure) {
                System.err.println(failure.getTrace());
            }
        });
        Result result;
        if ("--method".equals(args[0]) && args.length == 3) {
            result = junit.run(Request.method(Class.forName(args[1]), args[2]));
        } else if ("--safety".equals(args[0]) || "--classes".equals(args[0])) {
            Class<?>[] classes = new Class<?>[args.length - 1];
            for (int i = 1; i < args.length; i++) classes[i - 1] = Class.forName(args[i]);
            result = junit.run(classes);
        } else throw new IllegalArgumentException("Unsupported qualification request");
        boolean safety = "--safety".equals(args[0]);
        int executed = result.getRunCount() - skipped.size();
        boolean passed = result.wasSuccessful() && result.getIgnoreCount() == 0
            && (safety ? executed >= 314 && OPTIONAL.containsAll(skipped)
                       : executed > 0 && skipped.isEmpty());
        System.out.println("COMMON_QUALIFICATION_RESULT discovered=" + result.getRunCount()
            + " executed=" + executed + " failures=" + result.getFailureCount()
            + " ignored=" + result.getIgnoreCount() + " skipped=" + skipped.size()
            + " passed=" + passed);
        for (String item : skipped) System.out.println("OPTIONAL_EXTERNAL_HISTORICAL_SKIP " + item);
        System.exit(passed ? 0 : 2);
    }
}
