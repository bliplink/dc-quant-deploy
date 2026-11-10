package com.app.dc.service.strategy.research;

/** Launch batching only: invoke the unchanged validator and parity CLI with fresh per-call state. */
public final class FourProfileParityBatchCli {
    public static void main(String[] args) throws Exception {
        if (args.length != 10) {
            throw new IllegalArgumentException("source family strategy bars symbol begin end hypothesis jar entry required");
        }
        RepresentativeSignalParityCli.main(new String[]{"--validate-source", args[0], args[1], args[2]});
        for (int profile = 0; profile < 4; profile++) {
            System.out.println("RISK_PROFILE_BEGIN " + profile);
            RepresentativeSignalParityCli.main(new String[]{args[3], args[4], args[5], args[6],
                    args[7], args[8], args[9], Integer.toString(profile)});
            System.out.println("RISK_PROFILE_END " + profile);
        }
    }
}
