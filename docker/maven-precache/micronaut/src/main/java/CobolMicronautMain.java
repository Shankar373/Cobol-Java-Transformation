import io.micronaut.context.ApplicationContext;

/** Runs the COBOL run unit inside a Micronaut application context. */
public class CobolMicronautMain {
    public static void main(String[] args) throws Exception {
        try (ApplicationContext context = ApplicationContext.run()) {
            Precache.main(args);
        }
    }
}
