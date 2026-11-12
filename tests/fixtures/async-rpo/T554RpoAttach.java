import com.sun.tools.attach.VirtualMachine;

/** Loads the bounded test fault helper into the explicitly selected JVM. */
public final class T554RpoAttach {
    public static void main(String[] arguments) throws Exception {
        if (arguments.length != 3) throw new IllegalArgumentException("Expected PID, agent JAR and control arguments");
        VirtualMachine target = VirtualMachine.attach(arguments[0]);
        try { target.loadAgent(arguments[1], arguments[2]); }
        finally { target.detach(); }
    }
}
