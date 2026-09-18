public class PidStress {
    public static void main(String[] args) {
        System.out.println("PID_STRESS_START");
        int processes = 0;
        Process[] procs = new Process[300];
        try {
            for (int i = 0; i < 300; i++) {
                String os = System.getProperty("os.name").toLowerCase();
                ProcessBuilder pb;
                if (os.contains("win")) {
                    pb = new ProcessBuilder("cmd", "/c", "timeout", "60");
                } else {
                    pb = new ProcessBuilder("sleep", "60");
                }
                pb.redirectErrorStream(true);
                procs[i] = pb.start();
                processes++;
                System.out.println("PROCESS_STARTED:" + processes);
            }
        } catch (Exception e) {
            System.out.println("PID_LIMIT_HIT:" + e.getClass().getSimpleName() + ":after=" + processes);
        } finally {
            for (int i = 0; i < procs.length; i++) {
                if (procs[i] != null) {
                    procs[i].destroyForcibly();
                }
            }
        }
        System.out.println("PID_STRESS_END:total=" + processes);
    }
}
