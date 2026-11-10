import com.app.dc.service.strategy.generate.StrategyGeneratedSourceValidator;
import com.app.dc.service.strategy.generate.StrategyCompileException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.Base64;

/** Batch diagnostics only: invokes the unchanged production source validator. */
public final class StrategySourceContractAuditCli {
    public static void main(String[] args) throws Exception {
        for (String line : Files.readAllLines(Paths.get(args[0]), StandardCharsets.UTF_8)) {
            String[] cells = line.split("\t");
            String source = new String(Files.readAllBytes(Paths.get(cells[1])), StandardCharsets.UTF_8);
            try {
                StrategyGeneratedSourceValidator.validate(source, cells[2], cells[3]);
                System.out.println(cells[0] + "\tPASS");
            } catch (StrategyCompileException failure) {
                System.out.println(cells[0] + "\tFAIL\t" + Base64.getEncoder().encodeToString(
                    failure.getCompileLog().getBytes(StandardCharsets.UTF_8)));
            }
        }
    }
}
