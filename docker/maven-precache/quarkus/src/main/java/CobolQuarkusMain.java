import io.quarkus.runtime.Quarkus;
import io.quarkus.runtime.QuarkusApplication;
import io.quarkus.runtime.annotations.QuarkusMain;

/** Runs the COBOL run unit inside the Quarkus runtime (command mode). */
@QuarkusMain
public class CobolQuarkusMain implements QuarkusApplication {
    @Override
    public int run(String... args) throws Exception {
        Precache.main(args);
        return 0;
    }

    public static void main(String... args) {
        Quarkus.run(CobolQuarkusMain.class, args);
    }
}
